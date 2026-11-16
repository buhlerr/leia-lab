"""Seed idempotente do tipo locacao_residencial a partir dos DEFAULT_* (M1)."""

from __future__ import annotations

import json

from src.db import defaults
from src.db.connection import init_db
from src.db.seed import seed_defaults
from src.graphs import analyze_minuta_graph as g
from src.graphs.minuta_rules import DEFAULT_RISCOS, DEFAULT_TEMA_MAP, DEFAULT_TEMAS


async def test_seed_creates_type_themes_risks_and_prompts(pool):
    await init_db(pool)
    assert await seed_defaults(pool) is True

    assert await pool.fetchval("SELECT slug FROM minuta_types") == defaults.LOCACAO_RESIDENCIAL
    themes = {r["slug"]: list(r["norm_ids"]) for r in await pool.fetch("SELECT slug, norm_ids FROM themes")}
    assert themes == {t: DEFAULT_TEMA_MAP.get(t, []) for t in DEFAULT_TEMAS}

    risks = {
        r["risk_id"]: r
        for r in await pool.fetch(
            "SELECT r.risk_id, t.slug, r.criticality, r.norms FROM risk_matrix r JOIN themes t ON t.id = r.theme_id"
        )
    }
    expected = {x["id"]: (tema, x) for tema, lista in DEFAULT_RISCOS.items() for x in lista}
    assert set(risks) == set(expected)
    for rid, (tema, x) in expected.items():
        assert (risks[rid]["slug"], risks[rid]["criticality"]) == (tema, x["cor"])
        assert json.loads(risks[rid]["norms"]) == x["normas"]

    kinds = {r["kind"]: r["prompt_text"] for r in await pool.fetch("SELECT kind, prompt_text FROM prompts")}
    assert kinds == defaults.DEFAULT_PROMPTS


async def test_seed_is_a_noop_once_the_type_exists_and_never_overwrites_edits(pool):
    await init_db(pool)
    await seed_defaults(pool)
    await pool.execute("UPDATE risk_matrix SET criticality = 'vermelho' WHERE risk_id = 'R-04'")
    history = await pool.fetchval("SELECT count(*) FROM domain_history")

    assert await seed_defaults(pool) is False
    await init_db(pool)

    assert await pool.fetchval("SELECT count(*) FROM risk_matrix") == sum(map(len, DEFAULT_RISCOS.values()))
    assert await pool.fetchval("SELECT criticality FROM risk_matrix WHERE risk_id = 'R-04'") == "vermelho"
    assert await pool.fetchval("SELECT count(*) FROM domain_history") == history


def test_seed_prompts_match_what_the_graph_uses_today():
    """Guarda de deriva ate a M2a, quando o grafo passa a ler a tabela prompts."""
    assert defaults.SISTEMA_REDIGIR == g.SISTEMA_REDIGIR
    assert defaults.TRIAGEM_RISCO == g._Q_RISCO["instructions"]
    assert defaults.REGULA_NORMA == g._Q_REGULA["regula"]["instructions"]
    assert defaults.LOCACAO_CLASSIFIER == g._Q_TIPO["tipo"]["criteria"][defaults.LOCACAO_RESIDENCIAL]
