"""M2a: o grafo roda sobre uma foto das regras lida do banco, gravada com cada analise."""

from __future__ import annotations

import json

import asyncpg
import pytest

import src.graphs.analyze_minuta_graph as mod
from src.db.connection import init_db
from src.db.defaults import LOCACAO_RESIDENCIAL as LOCACAO
from src.db.rules import RulesConfigError, load_rules_snapshot, verify_snapshot
from src.db.seed import seed_defaults
from src.graphs.minuta_rules import DEFAULT_RISCOS, DEFAULT_TEMA_MAP, DEFAULT_TEMAS
from tests.conftest import TEST_DATABASE_URL

MINUTA = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00 e demais encargos ajustados entre as partes.\n"
    "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M, "
    "conforme ajustado entre as partes neste instrumento contratual de locação residencial."
)


@pytest.fixture
async def seeded(pool):
    await init_db(pool)
    await seed_defaults(pool)
    return pool


async def _run(pool, settings, text=MINUTA, name="m.txt"):
    out = await mod.analyze(mod.build_analyze_minuta_graph(pool, settings), raw_text=text, filename=name)
    return out["analysis_id"], out


async def _psql(sql: str) -> None:
    """Escrita direta, por outra conexao, sem codigo da aplicacao (como um psql)."""
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


# ---------------------------------------------------------------- snapshot


async def test_snapshot_of_the_seed_matches_the_defaults(seeded):
    t = (await load_rules_snapshot(seeded)).content["types"][LOCACAO]
    assert t["temas"] == DEFAULT_TEMAS and t["tema_map"] == DEFAULT_TEMA_MAP
    assert t["riscos"] == {k: v for k, v in DEFAULT_RISCOS.items()}
    assert set(t["prompts"]) == {"redigir_system", "triagem_risco", "confirmar_risco", "regula_norma"}


async def test_versions_are_content_hashes_that_track_each_kind_of_change(seeded):
    s1 = await load_rules_snapshot(seeded)
    assert verify_snapshot(s1.content, s1.hash)
    assert not verify_snapshot({**s1.content, "history_id": -1}, s1.hash)
    again = await load_rules_snapshot(seeded)
    assert (again.hash, again.matrix_version, again.prompt_version) == (s1.hash, s1.matrix_version, s1.prompt_version)

    await _psql("UPDATE risk_matrix SET description = 'Periodicidade inferior a 6 meses' WHERE risk_id = 'R-01'")
    s2 = await load_rules_snapshot(seeded)
    assert s2.matrix_version != s1.matrix_version and s2.prompt_version == s1.prompt_version
    assert s2.history_id > s1.history_id

    await _psql("UPDATE prompts SET prompt_text = prompt_text || ' extra' WHERE kind = 'redigir_system'")
    s3 = await load_rules_snapshot(seeded)
    assert s3.prompt_version != s2.prompt_version and s3.matrix_version == s2.matrix_version

    # voltar ao conteudo antigo volta a mesma versao: e hash de conteudo, nao contador.
    await _psql("UPDATE risk_matrix SET description = 'Periodicidade de reajuste inferior a 1 ano' WHERE risk_id = 'R-01'")
    assert (await load_rules_snapshot(seeded)).matrix_version == s1.matrix_version


async def test_inactive_rows_are_left_out(seeded):
    await seeded.execute("UPDATE risk_matrix SET active = false WHERE risk_id = 'R-05'")
    t = (await load_rules_snapshot(seeded)).content["types"][LOCACAO]
    ids = {x["id"] for lst in t["riscos"].values() for x in lst}
    assert "R-05" not in ids and "R-01" in ids


# ---------------------------------------------------------------- criterio de aceite


async def test_edited_matrix_changes_the_version_and_the_old_analysis_keeps_its_rule(seeded, settings):
    a1, out1 = await _run(seeded, settings)
    sev1 = {x["risk_id"]: x["severity"] for x in out1["report_envelope"]["content"]["alerts"]}
    assert sev1["R-04"] == "yellow"  # o Jev offline sempre escolhe o 1o tema (benfeitorias)

    await _psql("UPDATE risk_matrix SET criticality = 'vermelho' WHERE risk_id = 'R-04'")
    a2, out2 = await _run(seeded, settings)
    sev2 = {x["risk_id"]: x["severity"] for x in out2["report_envelope"]["content"]["alerts"]}
    assert sev2["R-04"] == "red"  # a proxima analise usa a matriz editada

    r1, r2 = [await seeded.fetchrow("SELECT * FROM analyses WHERE id = $1::uuid", i) for i in (a1, a2)]
    assert r1["matrix_version"] != r2["matrix_version"]
    assert r1["prompt_version"] == r2["prompt_version"]
    stored = json.loads(r1["rules_snapshot"])
    assert verify_snapshot(stored, r1["rules_hash"])
    old_rule = stored["types"][LOCACAO]["riscos"]["benfeitorias_e_conservacao"][0]
    assert (old_rule["id"], old_rule["cor"]) == ("R-04", "amarelo")  # a regra que decidiu a analise antiga
    assert json.loads(r1["report"])["content"]["alerts"][0]["severity"] == "yellow"
    # a marca do historico separa exatamente a mudanca feita entre as duas
    changed = await seeded.fetch(
        "SELECT new_row FROM domain_history WHERE id > $1 AND id <= $2", r1["domain_history_id"], r2["domain_history_id"]
    )
    assert [json.loads(c["new_row"])["criticality"] for c in changed] == ["vermelho"]


async def test_analysis_row_records_params_status_and_masked_alias(seeded, settings):
    aid, out = await _run(seeded, settings, name="Contrato Joao da Silva.txt")
    row = await seeded.fetchrow("SELECT * FROM analyses WHERE id = $1::uuid", aid)
    assert (row["status"], row["minuta_type"]) == ("done", LOCACAO) and row["finished_at"] is not None
    assert json.loads(row["params"])["confirm_cutoff"] == 0.5
    assert row["filename_alias"].startswith("documento-") and "Joao" not in row["filename_alias"]
    assert row["rules_hash"] == out["rules_meta"]["hash"]


async def test_unsupported_document_is_recorded_too(seeded, settings):
    aid, _ = await _run(seeded, settings, text="ATA DE ASSEMBLEIA GERAL EXTRAORDINARIA DE SOCIEDADE.", name="ata.txt")
    assert await seeded.fetchval("SELECT status FROM analyses WHERE id = $1::uuid", aid) == "unsupported"


# ---------------------------------------------------------------- regras vem do banco


async def test_prompts_edited_in_the_db_reach_the_next_run(seeded, settings, monkeypatch):
    jev_instr: list[str] = []
    systems: list[str] = []
    real_jev, real_llm = mod.call_jev, mod.chat_completion

    async def spy_jev(state, questions, settings=None):
        jev_instr.extend(q["instructions"] for q in questions.values())
        return await real_jev(state, questions, settings)

    async def spy_llm(system, user, settings=None, **kw):
        systems.append(system)
        return await real_llm(system, user, settings, **kw)

    monkeypatch.setattr(mod, "call_jev", spy_jev)
    monkeypatch.setattr(mod, "chat_completion", spy_llm)
    await _psql("UPDATE prompts SET prompt_text = 'REDATOR NOVO. alertas' WHERE kind = 'redigir_system'")
    await _psql("UPDATE prompts SET prompt_text = 'TRIAGEM NOVA?' WHERE kind = 'triagem_risco'")
    await _psql("UPDATE prompts SET prompt_text = 'CONFIRMA {risco}?' WHERE kind = 'confirmar_risco'")
    await _run(seeded, settings)

    assert systems and set(systems) == {"REDATOR NOVO. alertas"}
    assert "TRIAGEM NOVA?" in jev_instr
    assert any(i.startswith("CONFIRMA ") and i.endswith("?") and "{risco}" not in i for i in jev_instr)


async def test_classifier_candidates_come_from_minuta_types(seeded, settings, monkeypatch):
    await seeded.execute(
        "INSERT INTO minuta_types (slug, name, classifier_description) "
        "VALUES ('compra_venda', 'Compra e venda', 'Contrato de compra e venda de imovel')"
    )
    tid = await seeded.fetchval("SELECT id FROM minuta_types WHERE slug = 'compra_venda'")
    await seeded.execute(
        "INSERT INTO prompts (minuta_type_id, kind, prompt_text) SELECT $1, kind, prompt_text FROM prompts "
        "WHERE minuta_type_id <> $1",
        tid,
    )
    asked: list[dict] = []
    real = mod.call_jev

    async def spy(state, questions, settings=None):
        if "tipo" in questions:
            asked.append(questions["tipo"]["criteria"])
        return await real(state, questions, settings)

    monkeypatch.setattr(mod, "call_jev", spy)
    await _run(seeded, settings)
    assert set(asked[0]) == {LOCACAO, "compra_venda", "nao_suportado"}
    assert asked[0]["compra_venda"] == "Contrato de compra e venda de imovel"


# ---------------------------------------------------------------- falha alto


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        ("UPDATE prompts SET active = false WHERE kind = 'confirmar_risco'", "confirmar_risco"),
        ("DELETE FROM prompts WHERE kind = 'regula_norma'", "regula_norma"),
        ("UPDATE minuta_types SET active = false", "nenhum tipo"),
    ],
)
async def test_missing_rules_fail_before_any_external_call_or_analysis_row(seeded, settings, monkeypatch, setup, match):
    async def boom(*a, **k):
        raise AssertionError("nenhuma chamada externa com regra faltando")

    monkeypatch.setattr(mod, "call_jev", boom)
    monkeypatch.setattr(mod, "chat_completion", boom)
    await seeded.execute(setup)
    with pytest.raises(RulesConfigError, match=match):
        await _run(seeded, settings)
    assert await seeded.fetchval("SELECT count(*) FROM analyses") == 0


async def test_empty_database_fails_loudly(pool, settings):
    await init_db(pool)
    with pytest.raises(RulesConfigError, match="seed_defaults"):
        await _run(pool, settings)
