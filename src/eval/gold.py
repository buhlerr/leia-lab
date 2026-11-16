"""Minimal gold set: expected risk ids per clause, a scorer, and a two-version comparison.

The committed ``gold/gold_set.json`` holds NO minuta text: only file name + sha256, the clause index
(as produced by ``segment_clauses`` over the MASKED text), a sha256 of that clause, and the expected
risk ids. The minutas themselves stay outside git (``LEIA_MINUTAS_DIR``) and are read by absolute path.

Labels are prototype labels written by the foundation worker, NOT lawyer-validated.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from src.graphs.minuta_rules import segment_clauses
from src.ingest.masking import mask_personal_data

GOLD_PATH = Path(__file__).resolve().parents[2] / "gold" / "gold_set.json"
Key = tuple[str, int]  # (minuta file name, clause number)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def minutas_dir() -> Path:
    d = os.environ.get("LEIA_MINUTAS_DIR")
    if not d:
        raise RuntimeError("set LEIA_MINUTAS_DIR to the folder with the masked minutas (they are never committed)")
    return Path(d)


def masked_clauses(path: Path) -> list[str]:
    """Same text the graph segments: mask first, then ``segment_clauses``."""
    return segment_clauses(mask_personal_data(path.read_text(encoding="utf-8")))


def load_gold(path: Path = GOLD_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_gold(gold: dict[str, Any], directory: Path) -> list[str]:
    """Problems between the gold file and the local minutas (empty list = aligned)."""
    problems: list[str] = []
    cache: dict[str, list[str]] = {}
    for name, meta in gold["minutas"].items():
        p = directory / name
        if not p.is_file():
            problems.append(f"{name}: missing")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != meta["sha256"]:
            problems.append(f"{name}: file hash differs")
        else:
            cache[name] = masked_clauses(p)
    for c in gold["clauses"]:
        cl = cache.get(c["file"])
        if cl is None:
            continue
        if c["clause_n"] > len(cl) or sha256_text(cl[c["clause_n"] - 1]) != c["clause_sha256"]:
            problems.append(f"{c['id']}: clause {c['file']}#{c['clause_n']} does not match (segmentation/masking changed?)")
    return problems


def build_gold(directory: Path, labels: list[tuple[str, int, list[str]]], note: str) -> dict[str, Any]:
    """Build the gold JSON from ``(file, clause_n, expected_ids)`` labels. Run locally, commit the result."""
    minutas: dict[str, Any] = {}
    clauses: list[dict[str, Any]] = []
    for i, (name, n, expected) in enumerate(labels, start=1):
        p = directory / name
        minutas.setdefault(name, {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        text = masked_clauses(p)[n - 1]
        clauses.append(
            {"id": f"g{i:02d}", "file": name, "clause_n": n, "clause_sha256": sha256_text(text), "expected": sorted(expected)}
        )
    return {"version": 1, "note": note, "minutas": minutas, "clauses": clauses}


def detected_from_report(report: dict[str, Any]) -> dict[int, set[str]]:
    """``{clause_n: {risk ids}}`` from a report envelope (``analyses.report``)."""
    out: dict[int, set[str]] = {}
    for a in (report.get("content") or {}).get("alerts", []):
        out.setdefault(a["clause_index"], set()).add(a["risk_id"])
    return out


def score(gold: dict[str, Any], detected: dict[Key, set[str]]) -> dict[str, Any]:
    """Expected vs detected risk ids over the gold clauses (micro precision/recall/F1 + exact-match rate)."""
    tp = fp = fn = exact = 0
    per_clause: dict[str, dict[str, Any]] = {}
    for c in gold["clauses"]:
        exp, got = set(c["expected"]), set(detected.get((c["file"], c["clause_n"]), set()))
        tp, fp, fn = tp + len(exp & got), fp + len(got - exp), fn + len(exp - got)
        exact += exp == got
        per_clause[c["id"]] = {"expected": sorted(exp), "detected": sorted(got), "missed": sorted(exp - got), "extra": sorted(got - exp)}
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
        "exact_match": f"{exact}/{len(gold['clauses'])}",
        "per_clause": per_clause,
    }


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Metric deltas (b - a) and the clauses whose detection changed between two scored versions."""
    delta = {k: round(b[k] - a[k], 3) for k in ("precision", "recall", "f1")}
    changed = {
        cid: {"from": a["per_clause"][cid]["detected"], "to": b["per_clause"][cid]["detected"],
              "expected": a["per_clause"][cid]["expected"]}
        for cid in a["per_clause"]
        if a["per_clause"][cid]["detected"] != b["per_clause"][cid]["detected"]
    }
    return {"delta": delta, "changed_clauses": changed}


async def detected_from_analyses(pool: Any, analyses: dict[str, str]) -> dict[Key, set[str]]:
    """Read detections from stored analyses (``{minuta file: analysis_id}``): comparable across matrix versions."""
    out: dict[Key, set[str]] = {}
    for name, aid in analyses.items():
        rep = await pool.fetchval("SELECT report FROM analyses WHERE id = $1::uuid", aid)
        for n, ids in detected_from_report(json.loads(rep) if isinstance(rep, str) else rep or {}).items():
            out[(name, n)] = ids
    return out
