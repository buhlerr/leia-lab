"""Gold set scorer + two-version comparison; the committed gold file holds no minuta text."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.eval import gold as G

GOLD = {
    "clauses": [
        {"id": "g01", "file": "a.txt", "clause_n": 1, "expected": ["R-03"]},
        {"id": "g02", "file": "a.txt", "clause_n": 2, "expected": []},
        {"id": "g03", "file": "b.txt", "clause_n": 1, "expected": ["R-04", "R-02"]},
    ]
}

# the two committed clauses that declare expected_severity (g05 and g17 of gold/gold_set.json)
SEV_GOLD = {
    "clauses": [
        {"id": "g05", "file": "locacao-02.txt", "clause_n": 6, "expected": ["R053", "R054"], "expected_severity": {"R054": "red"}},
        {
            "id": "g17", "file": "locacao-01.txt", "clause_n": 1, "expected": ["R001", "R006", "R007"],
            "expected_severity": {"R001": "yellow", "R006": "yellow", "R007": "red"},
        },
    ]
}
SEV_GOLD_NO_DECLARATION = {"clauses": [{k: v for k, v in c.items() if k != "expected_severity"} for c in SEV_GOLD["clauses"]]}


def test_score_counts_tp_fp_fn_per_clause():
    det = {("a.txt", 1): {"R-03": "red"}, ("a.txt", 2): {"R-01": "yellow"}, ("b.txt", 1): {"R-04": "green"}}
    s = G.score(GOLD, det)
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert s["precision"] == 0.667 and s["recall"] == 0.667
    assert s["per_clause"]["g02"]["extra"] == ["R-01"] and s["per_clause"]["g03"]["missed"] == ["R-02"]
    assert s["exact_match"] == "1/3"


def test_perfect_and_empty_detection():
    perfect = {("a.txt", 1): {"R-03": "red"}, ("b.txt", 1): {"R-04": "yellow", "R-02": "green"}}
    assert G.score(GOLD, perfect)["f1"] == 1.0
    assert G.score(GOLD, {})["recall"] == 0.0


def test_compare_two_versions_reports_delta_and_changed_clauses():
    a = G.score(GOLD, {("a.txt", 1): {"R-03": "red"}, ("b.txt", 1): {"R-04": "red"}})
    b = G.score(GOLD, {("a.txt", 1): {"R-03": "red"}, ("b.txt", 1): {"R-04": "red", "R-02": "red"}})
    c = G.compare(a, b)
    assert c["delta"]["recall"] > 0 and c["delta"]["precision"] == 0.0
    assert list(c["changed_clauses"]) == ["g03"]
    assert c["changed_clauses"]["g03"]["to"] == ["R-02", "R-04"]


def test_detected_from_report():
    rep = {
        "content": {
            "alerts": [
                {"clause_index": 2, "risk_id": "R-01", "severity": "red"},
                {"clause_index": 2, "risk_id": "R-02", "severity": "green"},
            ]
        }
    }
    assert G.detected_from_report(rep) == {2: {"R-01": "red", "R-02": "green"}}


def test_red_detected_as_red_counts_as_correct_severity():
    det = {
        ("locacao-02.txt", 6): {"R053": "yellow", "R054": "red"},
        ("locacao-01.txt", 1): {"R001": "yellow", "R006": "yellow", "R007": "red"},
    }
    severity = G.score(SEV_GOLD, det)["severity"]
    assert (severity["compared"], severity["correct"], severity["wrong"]) == (4, 4, 0)
    assert severity["accuracy"] == 1.0
    assert severity["per_clause"] == {"g05": {"wrong": []}, "g17": {"wrong": []}}


def test_wrong_severity_is_listed_and_lowers_accuracy():
    det = {
        ("locacao-02.txt", 6): {"R053": "yellow", "R054": "yellow"},
        ("locacao-01.txt", 1): {"R001": "yellow", "R006": "yellow", "R007": "red"},
    }
    severity = G.score(SEV_GOLD, det)["severity"]
    assert (severity["compared"], severity["correct"], severity["wrong"]) == (4, 3, 1)
    assert severity["accuracy"] == 0.75
    assert severity["per_clause"]["g05"]["wrong"] == [{"risk_id": "R054", "expected": "red", "detected": "yellow"}]
    assert severity["per_clause"]["g17"]["wrong"] == []


def test_missing_detection_is_not_a_severity_error():
    # R007 not detected at all, so it stays an id error (fn) and is not severity-compared; accuracy rounds to 3 places.
    partial = {("locacao-02.txt", 6): {"R054": "green"}, ("locacao-01.txt", 1): {"R001": "yellow", "R006": "green"}}
    severity = G.score(SEV_GOLD, partial)["severity"]
    assert severity == {
        "compared": 3, "correct": 1, "wrong": 2, "accuracy": 0.333,
        "per_clause": {
            "g05": {"wrong": [{"risk_id": "R054", "expected": "red", "detected": "green"}]},
            "g17": {"wrong": [{"risk_id": "R006", "expected": "yellow", "detected": "green"}]},
        },
    }


def test_clause_without_expected_severity_contributes_nothing():
    det = {("a.txt", 1): {"R-03": "yellow"}, ("b.txt", 1): {"R-04": "green", "R-02": "red"}}
    assert G.score(GOLD, det)["severity"] == {"compared": 0, "correct": 0, "wrong": 0, "accuracy": None, "per_clause": {}}


def test_id_metrics_are_unchanged_by_the_severity_declaration():
    det = {
        ("locacao-02.txt", 6): {"R053": "yellow", "R054": "yellow"},
        ("locacao-01.txt", 1): {"R001": "yellow", "R006": "yellow"},  # R007 missing
    }
    declared, undeclared = G.score(SEV_GOLD, det), G.score(SEV_GOLD_NO_DECLARATION, det)
    assert (declared["f1"], declared["exact_match"]) == (0.889, "1/2")
    assert (declared["tp"], declared["fp"], declared["fn"]) == (4, 0, 1)
    assert (declared["f1"], declared["exact_match"]) == (undeclared["f1"], undeclared["exact_match"])
    assert declared["per_clause"] == undeclared["per_clause"]


def test_build_and_verify_gold_on_synthetic_minutas(tmp_path):
    (tmp_path / "m.txt").write_text(
        "CONTRATO DE LOCAÇÃO\nCláusula 1ª - Do Reajuste: " + "reajuste semestral do aluguel. " * 6
        + "\nCláusula 2ª - Da Multa: " + "multa de tres alugueis. " * 8, encoding="utf-8")
    g = G.build_gold(tmp_path, [("m.txt", 1, ["R-01"])], "t")
    assert G.verify_gold(g, tmp_path) == []
    (tmp_path / "m.txt").write_text("outro texto", encoding="utf-8")
    assert "file hash differs" in G.verify_gold(g, tmp_path)[0]


def test_committed_gold_set_is_big_enough_and_has_no_text():
    g = G.load_gold()
    assert len(g["clauses"]) >= 10 and 2 <= len(g["minutas"]) <= 3
    assert any(c["expected"] for c in g["clauses"]) and any(not c["expected"] for c in g["clauses"])
    required = {"id", "file", "clause_n", "clause_sha256", "expected"}
    assert all(required <= set(c) <= required | {"expected_severity"} for c in g["clauses"])
    assert Path(G.GOLD_PATH).stat().st_size < 6000  # ids and hashes only


def test_committed_severity_only_covers_declared_expected_ids():
    g = G.load_gold()
    declared = {c["id"]: c["expected_severity"] for c in g["clauses"] if "expected_severity" in c}
    assert declared == {
        "g05": {"R054": "red"},
        "g17": {"R001": "yellow", "R006": "yellow", "R007": "red"},
    }
    for c in g["clauses"]:
        severities = c.get("expected_severity") or {}
        assert set(severities) <= set(c["expected"]), f"{c['id']}: severidade de id nao esperado"
        assert set(severities.values()) <= {"red", "yellow", "green"}


@pytest.mark.skipif(not os.environ.get("LEIA_MINUTAS_DIR"), reason="local masked minutas not configured")
def test_committed_gold_set_matches_the_local_minutas():
    assert G.verify_gold(G.load_gold(), G.minutas_dir()) == []


def test_gold_expected_ids_exist_in_the_real_matrix():
    matrix = Path(G.GOLD_PATH).parents[1] / "data" / "matriz" / "v1.jsonl"
    ids = {json.loads(line)["id"] for line in matrix.read_text(encoding="utf-8").splitlines() if line.strip()}
    used = {risk for c in G.load_gold()["clauses"] for risk in c["expected"]}
    assert used <= ids, f"gold ids fora da matriz v1: {sorted(used - ids)}"
