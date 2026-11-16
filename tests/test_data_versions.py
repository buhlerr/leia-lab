"""M5 / Q5: matriz real e base normativa versionadas em data/ e aplicadas uma vez no banco."""

from __future__ import annotations

import json
import shutil

import pytest

from src.db.connection import init_db
from src.db.rules import load_rules_snapshot
from src.db.seed import seed_defaults
from src.db.versions import DATA_DIR, DataVersionError, apply_base, apply_matrix, read_base, read_matrix
from src.graphs.minuta_rules import load_risk_matrix, normalize_norm, validate_and_format

# --- normalizacao (bead leia-lab-vz3) -------------------------------------------------


def test_normalize_norm_maps_norma_artigo_and_keeps_extras():
    n = normalize_norm({"norma": "Lei 8.245/1991", "artigo": "35", "status": "presente", "por_que": "x"})
    assert n == {
        "norma": "Lei 8.245/1991",
        "artigo": "35",
        "status": "presente",
        "por_que": "x",
        "id": "lei-8245-1991-art-35",
        "citacao": "Lei 8.245/1991, art. 35",
    }
    assert normalize_norm({"norma": "ABNT NBR 16.280"})["citacao"] == "ABNT NBR 16.280"
    assert normalize_norm({"citacao": "Lei X, art. 1", "id": "n1"}) == {"id": "n1", "citacao": "Lei X, art. 1"}
    kb = {"Lei 10.406/2002, art. 653": "codigo-civil-2002-art-653"}
    assert normalize_norm({"norma": "Lei 10.406/2002", "artigo": "653"}, kb_ids=kb)["id"] == "codigo-civil-2002-art-653"


@pytest.mark.parametrize("bad", [{"status": "presente"}, "Lei 1", None])
def test_normalize_norm_raises_instead_of_dropping(bad):
    with pytest.raises(ValueError, match="R-9"):
        normalize_norm(bad, risk_id="R-9")


def test_load_risk_matrix_keeps_every_norm_of_the_real_format(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text(
        json.dumps({"id": "R001", "tema": "t", "risco": "r", "criticidade_sugerida": "vermelho",
                    "parte_prejudicada": "locatario", "normas": [{"norma": "Lei 8.245/1991", "artigo": "22"}]})
        + "\n",
        encoding="utf-8",
    )
    _, riscos, tema_map = load_risk_matrix(p)
    assert riscos["t"][0]["normas"][0]["citacao"] == "Lei 8.245/1991, art. 22"
    assert tema_map == {"t": ["lei-8245-1991-art-22"]}


def test_downgrade_without_norm_is_explained():
    doc = {
        "filename": "x.txt", "tipo": "locacao_residencial", "suportado": True,
        "clausulas": [{"n": 1, "texto": "clausula", "tema": "t",
                       "confirmados": [{"id": "R-1", "risco": "r", "cor": "vermelho", "parte": "locatario", "normas": []}],
                       "analise": {"alertas": [{"id": "R-1", "trecho": "clausula"}]}}],
    }
    _, env, _ = validate_and_format(doc)
    (alert,) = env["content"]["alerts"]
    assert alert["severity"] == "yellow" and "vermelho -> amarelo" in alert["downgraded"]


# --- arquivos versionados ---------------------------------------------------------------


def test_matrix_v1_reads_every_risk_and_norm():
    rows, sha = read_matrix("v1")
    raw = [json.loads(line) for line in (DATA_DIR / "matriz" / "v1.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == len(raw) == 185 and len({t for t, _ in rows}) == 31
    assert sum(len(x["normas"]) for _, x in rows) == sum(len(r["normas"]) for r in raw) == 503
    assert all(x["normas"] for _, x in rows if x["cor"] == "vermelho"), "vermelho sem norma seria rebaixado"
    assert len(sha) == 64


def test_matrix_v2_reflects_the_lawyer_review():
    rows, sha = read_matrix("v2")
    raw = [json.loads(line) for line in (DATA_DIR / "matriz" / "v2.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == len(raw) == 184 and len({t for t, _ in rows}) == 31
    by_id = {x["id"]: x for _, x in rows}
    assert "R176" not in by_id
    assert by_id["R054"]["cor"] == "vermelho"
    assert by_id["R007"]["cor"] == "amarelo"
    assert all(x["normas"] for _, x in rows if x["cor"] == "vermelho")
    assert len(sha) == 64


def test_base_v1_reads_every_article_with_unique_citation():
    artigos, _ = read_base("v1")
    assert len(artigos) == 330
    assert {"Lei 8.245/1991, art. 35", "Súmulas do STJ, art. Súmula 214"} <= {a["citacao"] for a in artigos}


def test_tampered_version_is_refused(tmp_path):
    shutil.copytree(DATA_DIR, tmp_path / "data")
    m = tmp_path / "data" / "matriz" / "v1.jsonl"
    m.write_text(m.read_text(encoding="utf-8").replace("vermelho", "amarelo", 1), encoding="utf-8")
    with pytest.raises(DataVersionError, match="sha256"):
        read_matrix("v1", tmp_path / "data")
    with pytest.raises(DataVersionError, match="manifesto"):
        read_matrix("v9")


# --- aplicacao no banco ------------------------------------------------------------------


async def _fake_ingest(pool):
    async def ingest_fn(texto: str, citacao: str, source: str) -> None:
        await pool.execute(
            "INSERT INTO kb_docs (title, source, metadata) VALUES ($1, $2, '{}'::jsonb)", citacao, source
        )

    return ingest_fn


async def test_apply_matrix_replaces_active_risks_once_and_audits(pool):
    await init_db(pool)
    await seed_defaults(pool)
    history = await pool.fetchval("SELECT count(*) FROM domain_history")

    assert await apply_matrix(pool, "v1") is True
    assert await pool.fetchval("SELECT count(*) FROM risk_matrix WHERE active") == 185
    assert await pool.fetchval("SELECT count(*) FROM risk_matrix WHERE NOT active") == 6  # padrao: desativado, nao apagado
    assert await pool.fetchval("SELECT count(*) FROM domain_history") > history
    norms = await pool.fetchval("SELECT norms FROM risk_matrix WHERE risk_id = 'R001'")
    assert {n["id"] for n in json.loads(norms)} >= {"codigo-civil-2002-art-653"}

    snap = await load_rules_snapshot(pool)
    t = snap.content["types"]["locacao_residencial"]
    assert len(t["temas"]) == 31  # temas padrao sem risco ativo ficam fora da foto
    assert sum(map(len, t["riscos"].values())) == 185

    assert await apply_matrix(pool, "v1") is False
    assert await pool.fetchval("SELECT count(*) FROM risk_matrix") == 191


async def test_apply_matrix_v2_transitions_from_v1(pool):
    await init_db(pool)
    await seed_defaults(pool)
    assert await apply_matrix(pool, "v1") is True
    assert await apply_matrix(pool, "v2", base_version="v1") is True

    active = await pool.fetch("SELECT risk_id, criticality FROM risk_matrix WHERE active")
    assert len(active) == 184
    by_id = {r["risk_id"]: r["criticality"] for r in active}
    assert "R176" not in by_id and by_id["R054"] == "vermelho"
    assert await pool.fetchval(
        "SELECT criticality FROM risk_matrix WHERE risk_id = 'R176' AND NOT active"
    ) == "amarelo"

    snap = await load_rules_snapshot(pool)
    t = snap.content["types"]["locacao_residencial"]
    assert sum(map(len, t["riscos"].values())) == 184
    assert await apply_matrix(pool, "v2", base_version="v1") is False


async def test_apply_matrix_refuses_a_changed_published_version(pool, tmp_path):
    await init_db(pool)
    await seed_defaults(pool)
    await pool.execute("INSERT INTO data_versions (name, sha256) VALUES ('matriz/v1', 'outro')")
    with pytest.raises(DataVersionError, match="versao publicada nao muda"):
        await apply_matrix(pool, "v1")
    with pytest.raises(Exception, match="not allowed"):
        await pool.execute("DELETE FROM data_versions")


async def test_apply_matrix_needs_the_seeded_type(pool):
    await init_db(pool)
    with pytest.raises(DataVersionError, match="seed_defaults"):
        await apply_matrix(pool, "v1")


async def test_apply_base_indexes_missing_articles_and_resumes(pool):
    await init_db(pool)
    ingest_fn = await _fake_ingest(pool)
    await ingest_fn("t", "Lei 8.245/1991, art. 35", "base-normativa/v1")  # rodada anterior interrompida

    assert await apply_base(pool, ingest_fn, "v1") == 329
    assert await pool.fetchval("SELECT count(*) FROM kb_docs") == 330
    assert await pool.fetchval("SELECT count(*) FROM data_versions WHERE name = 'base-normativa/v1'") == 1
    assert await apply_base(pool, ingest_fn, "v1") == 0
