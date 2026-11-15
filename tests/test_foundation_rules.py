"""Seed, vz3 norm handling, per-analysis rules snapshot and its immutability."""

from __future__ import annotations

import json

import asyncpg
import pytest

from src.foundation.rules import load_rules_snapshot, verify_snapshot
from src.foundation.seed import LOCACAO, load_matrix_jsonl, normalize_norm, rows_from_matrix_jsonl, seed_defaults
from src.foundation.trail import append_trail, finish_analysis, start_analysis
from src.graphs.minuta_rules import DEFAULT_RISCOS, DEFAULT_TEMA_MAP, DEFAULT_TEMAS, load_risk_matrix


async def test_seed_defaults_matches_master_constants_and_is_idempotent(fpool):
    assert await seed_defaults(fpool) is True
    assert await seed_defaults(fpool) is False
    assert await fpool.fetchval("SELECT count(*) FROM minuta_types") == 1
    assert await fpool.fetchval("SELECT count(*) FROM themes") == len(DEFAULT_TEMAS)
    assert await fpool.fetchval("SELECT count(*) FROM risk_matrix") == sum(len(v) for v in DEFAULT_RISCOS.values())
    assert await fpool.fetchval("SELECT count(*) FROM prompts") == 4
    snap = await load_rules_snapshot(fpool)
    t = snap.content["types"][LOCACAO]
    assert t["temas"] == DEFAULT_TEMAS
    assert t["tema_map"] == DEFAULT_TEMA_MAP
    assert t["riscos"]["reajuste_e_indexacao"][0]["normas"][0]["citacao"] == "Lei 10.192/2001, art. 2"
    assert "alertas" in t["prompts"]["redigir_system"]["text"]


# ---- bead leia-lab-vz3: real matrix uses norma/artigo, not citacao
_REAL_ROW = {
    "id": "R001", "tema": "pre_contratual_e_partes", "risco": "Locador sem poderes", "parte_prejudicada": "locatario",
    "criticidade_sugerida": "vermelho",
    "normas": [
        {"norma": "Lei 10.406/2002", "artigo": "653", "status": "presente", "por_que": "mandato"},
        {"norma": "Lei 8.245/1991", "artigo": "", "status": "a_confirmar", "por_que": "x"},
    ],
}


def test_normalize_norm_maps_norma_artigo_to_citacao_and_keeps_extras():
    n = normalize_norm(_REAL_ROW["normas"][0], risk_id="R001")
    assert n["citacao"] == "Lei 10.406/2002, art. 653" and n["id"]
    assert n["status"] == "presente" and n["por_que"] == "mandato"
    assert normalize_norm(_REAL_ROW["normas"][1])["citacao"] == "Lei 8.245/1991"  # no artigo
    assert normalize_norm({"citacao": "X, art. 1"})["citacao"] == "X, art. 1"


def test_normalize_norm_refuses_to_drop_an_unmappable_norm():
    with pytest.raises(ValueError, match="R9"):
        normalize_norm({"artigo": "3"}, risk_id="R9")


def test_masters_loader_drops_real_format_norms_but_ours_keeps_them(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text(json.dumps(_REAL_ROW) + "\n", encoding="utf-8")
    _, riscos, _ = load_risk_matrix(p)
    assert riscos["pre_contratual_e_partes"][0]["normas"] == []  # the bug: red becomes yellow downstream
    rows = rows_from_matrix_jsonl(p)
    assert [n["citacao"] for n in rows[0]["norms"]] == ["Lei 10.406/2002, art. 653", "Lei 8.245/1991"]


async def test_load_matrix_jsonl_into_db_keeps_norms(fpool, tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text(json.dumps(_REAL_ROW) + "\n", encoding="utf-8")
    assert await load_matrix_jsonl(fpool, "locacao_real", p) == 1
    snap = await load_rules_snapshot(fpool)
    risk = snap.content["types"]["locacao_real"]["riscos"]["pre_contratual_e_partes"][0]
    assert risk["cor"] == "vermelho" and len(risk["normas"]) == 2


# ---- snapshot
async def test_snapshot_hash_verifies_and_versions_track_changes(fpool):
    await seed_defaults(fpool)
    s1 = await load_rules_snapshot(fpool)
    assert verify_snapshot(s1.content, s1.hash)
    assert not verify_snapshot({**s1.content, "history_id": 0}, s1.hash)
    again = await load_rules_snapshot(fpool)
    assert (again.hash, again.matrix_version, again.prompt_version) == (s1.hash, s1.matrix_version, s1.prompt_version)

    await fpool.execute("UPDATE risk_matrix SET description = 'Periodicidade inferior a 6 meses' WHERE risk_id='R-01'")
    s2 = await load_rules_snapshot(fpool)
    assert s2.matrix_version != s1.matrix_version and s2.prompt_version == s1.prompt_version
    assert s2.history_id > s1.history_id and s2.hash != s1.hash

    await fpool.execute("UPDATE prompts SET prompt_text = prompt_text || ' extra' WHERE kind='redigir_system'")
    s3 = await load_rules_snapshot(fpool)
    assert s3.prompt_version != s2.prompt_version and s3.matrix_version == s2.matrix_version


async def test_inactive_rows_are_not_in_the_snapshot(fpool):
    await seed_defaults(fpool)
    await fpool.execute("UPDATE risk_matrix SET active = false WHERE risk_id = 'R-05'")
    snap = await load_rules_snapshot(fpool)
    ids = [x["id"] for lst in snap.content["types"][LOCACAO]["riscos"].values() for x in lst]
    assert "R-05" not in ids and "R-01" in ids


async def test_old_analysis_keeps_the_rules_that_decided_it_after_the_matrix_changes(fpool):
    await seed_defaults(fpool)
    snap = await load_rules_snapshot(fpool)
    aid = await start_analysis(fpool, snap, filename_alias="documento-aaaa.txt", masked_text="texto", params={"c": 1})
    await fpool.execute("UPDATE risk_matrix SET criticality='amarelo', description='NOVO' WHERE risk_id='R-01'")
    await fpool.execute("DELETE FROM risk_matrix WHERE risk_id='R-02'")

    row = await fpool.fetchrow("SELECT * FROM analyses WHERE id=$1", aid)
    stored = json.loads(row["rules_snapshot"])
    r01 = stored["types"][LOCACAO]["riscos"]["reajuste_e_indexacao"][0]
    assert r01["cor"] == "vermelho" and r01["risco"] != "NOVO"
    assert any(x["id"] == "R-02" for lst in stored["types"][LOCACAO]["riscos"].values() for x in lst)
    assert verify_snapshot(stored, row["rules_hash"])
    assert row["matrix_version"] == snap.matrix_version != (await load_rules_snapshot(fpool)).matrix_version
    # ... and the history says what changed, tied by the watermark stored with the analysis.
    later = await fpool.fetch(
        "SELECT op, table_name FROM domain_history WHERE id > $1 ORDER BY id", row["domain_history_id"]
    )
    assert [(r["table_name"], r["op"]) for r in later] == [("risk_matrix", "UPDATE"), ("risk_matrix", "DELETE")]


async def test_analysis_snapshot_columns_are_frozen_and_rows_undeletable(fpool):
    await seed_defaults(fpool)
    snap = await load_rules_snapshot(fpool)
    aid = await start_analysis(fpool, snap, filename_alias="d.txt", masked_text="t", params={})
    with pytest.raises(asyncpg.PostgresError):
        await fpool.execute("UPDATE analyses SET rules_snapshot = '{}'::jsonb WHERE id=$1", aid)
    with pytest.raises(asyncpg.PostgresError):
        await fpool.execute("UPDATE analyses SET matrix_version = 'x' WHERE id=$1", aid)
    with pytest.raises(asyncpg.PostgresError):
        await fpool.execute("DELETE FROM analyses WHERE id=$1", aid)
    await finish_analysis(fpool, aid, status="done", minuta_type=LOCACAO, report={"ok": True})
    row = await fpool.fetchrow("SELECT status, minuta_type, finished_at FROM analyses WHERE id=$1", aid)
    assert row["status"] == "done" and row["finished_at"] is not None


async def test_trail_is_append_only_with_sequential_steps_and_versions(fpool):
    await seed_defaults(fpool)
    snap = await load_rules_snapshot(fpool)
    aid = await start_analysis(fpool, snap, filename_alias="d.txt", masked_text="t", params={})
    await append_trail(fpool, aid, snap, [{"step": "classificar", "decision": {"tipo": LOCACAO}, "score": 0.9, "cutoff": 0.8}])
    await append_trail(
        fpool, aid, snap,
        [{"step": "triar", "clause_n": 1, "score": 0.7, "cutoff": 0.5, "cited_norms": ["Lei 8.245/1991, art. 4"]}],
    )
    rows = await fpool.fetch("SELECT * FROM analysis_trail WHERE analysis_id=$1 ORDER BY seq", aid)
    assert [r["seq"] for r in rows] == [1, 2]
    assert all(r["matrix_version"] == snap.matrix_version and r["prompt_version"] == snap.prompt_version for r in rows)
    assert rows[1]["cited_norms"] == ["Lei 8.245/1991, art. 4"]
    for sql in ("UPDATE analysis_trail SET step='x'", "DELETE FROM analysis_trail", "TRUNCATE analysis_trail"):
        with pytest.raises(asyncpg.PostgresError):
            await fpool.execute(sql)
