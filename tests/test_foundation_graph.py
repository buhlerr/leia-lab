"""The graph runs on DB rules and writes a trail that is rebuildable from the analysis id alone."""

from __future__ import annotations

import json

import pytest

import src.graphs.analyze_minuta_graph as mod
from src.foundation.rules import verify_snapshot
from src.foundation.seed import LOCACAO, seed_defaults
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

MINUTA = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00 e demais encargos ajustados entre as partes.\n"
    "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M, "
    "conforme ajustado entre as partes neste instrumento contratual de locação residencial."
)


async def _run(pool, settings, text=MINUTA, name="m.txt"):
    out = await analyze(build_analyze_minuta_graph(pool, settings), raw_text=text, filename=name)
    return out["analysis_id"], out


async def test_trail_is_rebuildable_from_the_analysis_id_alone(fpool, settings):
    await seed_defaults(fpool)
    aid, out = await _run(fpool, settings)
    a = await fpool.fetchrow("SELECT * FROM analyses WHERE id = $1::uuid", aid)
    assert a["status"] == "done" and a["minuta_type"] == LOCACAO and a["finished_at"] is not None
    assert verify_snapshot(json.loads(a["rules_snapshot"]), a["rules_hash"])
    assert json.loads(a["params"])["confirm_cutoff"] == 0.5

    trail = await fpool.fetch("SELECT * FROM analysis_trail WHERE analysis_id = $1::uuid ORDER BY seq", aid)
    steps = [r["step"] for r in trail]
    assert steps[:3] == ["iniciar", "classificar", "ficha"] and steps[-1] == "validar"
    assert {"triar", "analisar"} <= set(steps)
    assert [r["seq"] for r in trail] == list(range(1, len(trail) + 1))
    assert all(r["matrix_version"] == a["matrix_version"] and r["prompt_version"] == a["prompt_version"] for r in trail)
    cls = next(r for r in trail if r["step"] == "classificar")
    assert (cls["score"], cls["cutoff"]) == (0.95, 0.8)
    triar = [r for r in trail if r["step"] == "triar"]
    assert [r["clause_n"] for r in triar] == [c["n"] for c in out["clausulas"]]
    assert all(r["cutoff"] == 0.2 and r["score"] is not None for r in triar)
    validar = next(r for r in trail if r["step"] == "validar")
    assert json.loads(validar["decision"])["alerts"]  # the decision per alert is on the trail


async def test_next_analysis_uses_the_edited_matrix_and_the_old_one_keeps_its_own(fpool, settings):
    await seed_defaults(fpool)
    a1, out1 = await _run(fpool, settings)
    sev1 = {x["risk_id"]: x["severity"] for x in out1["report_envelope"]["content"]["alerts"]}
    assert sev1["R-04"] == "yellow"  # offline Jev always picks the first theme (benfeitorias)

    # a "direct psql" edit: no application code involved
    await fpool.execute("UPDATE risk_matrix SET criticality='vermelho' WHERE risk_id='R-04'")
    a2, out2 = await _run(fpool, settings)
    sev2 = {x["risk_id"]: x["severity"] for x in out2["report_envelope"]["content"]["alerts"]}
    assert sev2["R-04"] == "red"

    r1, r2 = [await fpool.fetchrow("SELECT * FROM analyses WHERE id=$1::uuid", i) for i in (a1, a2)]
    assert r1["matrix_version"] != r2["matrix_version"]
    old = json.loads(r1["rules_snapshot"])["types"][LOCACAO]["riscos"]["benfeitorias_e_conservacao"][0]
    assert old["cor"] == "amarelo"  # the old analysis still shows the rule that decided it
    assert json.loads(r1["report"])["content"]["alerts"][0]["severity"] == "yellow"
    changed = await fpool.fetch("SELECT old_row, new_row FROM domain_history WHERE id > $1 AND id <= $2",
                                r1["domain_history_id"], r2["domain_history_id"])
    assert len(changed) == 1 and json.loads(changed[0]["new_row"])["criticality"] == "vermelho"


async def test_prompt_edited_in_the_db_reaches_the_next_run(fpool, settings, monkeypatch):
    await seed_defaults(fpool)
    seen: list[str] = []
    real = mod.chat_completion

    async def spy(system, user, settings=None, **kw):
        seen.append(system)
        return await real(system, user, settings, **kw)

    monkeypatch.setattr(mod, "chat_completion", spy)
    await fpool.execute("UPDATE prompts SET prompt_text = 'PROMPT NOVO. alertas' WHERE kind='redigir_system'")
    await _run(fpool, settings)
    assert seen and all(s == "PROMPT NOVO. alertas" for s in seen)


async def test_classifier_candidates_come_from_minuta_types_rows(fpool, settings, monkeypatch):
    await seed_defaults(fpool)
    await fpool.execute(
        "INSERT INTO minuta_types (slug, name, classifier_description) VALUES ('compra_venda', 'Compra e venda', 'Contrato de compra e venda de imovel')"
    )
    asked: list[dict] = []
    real = mod.call_jev

    async def spy(state, questions, settings=None):
        if "tipo" in questions:
            asked.append(questions["tipo"]["criteria"])
        return await real(state, questions, settings)

    monkeypatch.setattr(mod, "call_jev", spy)
    await _run(fpool, settings)
    assert set(asked[0]) == {LOCACAO, "compra_venda", "nao_suportado"}
    assert asked[0]["compra_venda"] == "Contrato de compra e venda de imovel"


async def test_unsupported_document_stops_the_trail_at_validar(fpool, settings):
    await seed_defaults(fpool)
    aid, out = await _run(fpool, settings, text="ATA DE ASSEMBLEIA GERAL EXTRAORDINARIA DE SOCIEDADE.", name="ata.txt")
    assert (await fpool.fetchval("SELECT status FROM analyses WHERE id=$1::uuid", aid)) == "unsupported"
    steps = [r["step"] for r in await fpool.fetch("SELECT step FROM analysis_trail WHERE analysis_id=$1::uuid ORDER BY seq", aid)]
    assert steps == ["iniciar", "classificar", "validar"]


async def test_missing_prompt_fails_loudly_and_marks_the_analysis_failed_without_text(fpool, settings):
    await seed_defaults(fpool)
    await fpool.execute("DELETE FROM prompts WHERE kind='confirmar_risco'")
    with pytest.raises(KeyError):
        await _run(fpool, settings)
    row = await fpool.fetchrow("SELECT status, report FROM analyses")
    assert row["status"] == "failed"
    assert json.loads(row["report"]) == {"error": "KeyError", "step": "triar"}
