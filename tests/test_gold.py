"""Gold set scorer + two-version comparison; the committed gold file holds no minuta text."""

from __future__ import annotations

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


def test_score_counts_tp_fp_fn_per_clause():
    det = {("a.txt", 1): {"R-03"}, ("a.txt", 2): {"R-01"}, ("b.txt", 1): {"R-04"}}
    s = G.score(GOLD, det)
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert s["precision"] == 0.667 and s["recall"] == 0.667
    assert s["per_clause"]["g02"]["extra"] == ["R-01"] and s["per_clause"]["g03"]["missed"] == ["R-02"]
    assert s["exact_match"] == "1/3"


def test_perfect_and_empty_detection():
    perfect = {("a.txt", 1): {"R-03"}, ("b.txt", 1): {"R-04", "R-02"}}
    assert G.score(GOLD, perfect)["f1"] == 1.0
    assert G.score(GOLD, {})["recall"] == 0.0


def test_compare_two_versions_reports_delta_and_changed_clauses():
    a = G.score(GOLD, {("a.txt", 1): {"R-03"}, ("b.txt", 1): {"R-04"}})
    b = G.score(GOLD, {("a.txt", 1): {"R-03"}, ("b.txt", 1): {"R-04", "R-02"}})
    c = G.compare(a, b)
    assert c["delta"]["recall"] > 0 and c["delta"]["precision"] == 0.0
    assert list(c["changed_clauses"]) == ["g03"]
    assert c["changed_clauses"]["g03"]["to"] == ["R-02", "R-04"]


def test_detected_from_report():
    rep = {"content": {"alerts": [{"clause_index": 2, "risk_id": "R-01"}, {"clause_index": 2, "risk_id": "R-02"}]}}
    assert G.detected_from_report(rep) == {2: {"R-01", "R-02"}}


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
    assert {k for c in g["clauses"] for k in c} == {"id", "file", "clause_n", "clause_sha256", "expected"}
    assert Path(G.GOLD_PATH).stat().st_size < 6000  # ids and hashes only


@pytest.mark.skipif(not os.environ.get("LEIA_MINUTAS_DIR"), reason="local masked minutas not configured")
def test_committed_gold_set_matches_the_local_minutas():
    assert G.verify_gold(G.load_gold(), G.minutas_dir()) == []
