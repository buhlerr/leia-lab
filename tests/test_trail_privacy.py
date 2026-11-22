"""M2b: trilha reconstruivel pelo analysis_id e nenhum dado pessoal fora da maquina local."""

from __future__ import annotations

import json
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import src.graphs.analyze_minuta_graph as mod
from src.db.connection import init_db
from src.db.defaults import LOCACAO_RESIDENCIAL as LOCACAO
from src.db.rules import verify_snapshot
from src.db.seed import seed_defaults
from src.graphs.analyze_minuta_graph import AnalyzeMinutaState, analyze, analyze_stream, build_analyze_minuta_graph
from src.ingest import masking

NAME = "Carlos Eduardo Mendes"
CPF = "999.888.777-66"
EMAIL = "carlos.mendes@exemplo.com.br"
FILE_NAME = "minuta_Carlos_Eduardo_Mendes.txt"
RAW = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    f"LOCADOR: {NAME}, brasileiro, casado, CPF {CPF}, e-mail {EMAIL}.\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00 e demais encargos ajustados entre as partes.\n"
    "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M, "
    f"conforme ajustado entre as partes e {NAME}, CPF {CPF}, neste instrumento contratual de locação."
)
SECRETS = [NAME, "Mendes", CPF, "99988877766", EMAIL, FILE_NAME, "Carlos_Eduardo"]


@pytest.fixture
async def seeded(pool):
    await init_db(pool)
    await seed_defaults(pool)
    return pool


def _found(blob: str) -> list[str]:
    low = blob.lower()
    return [s for s in SECRETS if s.lower() in low]


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


async def _leaks(pool, settings) -> tuple[dict[str, list[str]], dict]:
    """Roda uma analise com checkpointer + stream e varre os 6 lugares; devolve {lugar: segredos achados}."""
    saver = InMemorySaver()
    graph = build_analyze_minuta_graph(pool, settings, checkpointer=saver)
    cfg = {"configurable": {"thread_id": "t1"}}
    updates = [c async for c in analyze_stream(graph, raw_text=RAW, filename=FILE_NAME, config=cfg)]
    final = (await graph.aget_state(cfg)).values
    checkpoints = [s async for s in graph.aget_state_history(cfg)]
    assert len(checkpoints) > 3 and final.get("suportado") is True  # a analise passou por todos os passos

    trail = [r["j"] for r in await pool.fetch("SELECT to_jsonb(t)::text AS j FROM analysis_trail t")]
    analysis = await pool.fetchrow("SELECT rules_snapshot::text AS s, report::text AS r, to_jsonb(a)::text AS row FROM analyses a")
    places = {
        "estado": _dump(final),
        "checkpoint": _dump([c.values for c in checkpoints]) + repr([c.metadata for c in checkpoints]) + repr(saver.storage),
        "updates por no": _dump(updates),
        "trilha": "\n".join(trail),
        "snapshot": analysis["s"],
        "relatorio": analysis["r"] + analysis["row"],
    }
    return {k: _found(v) for k, v in places.items()}, final


# ---------------------------------------------------------------- privacidade


def test_graph_state_schema_has_no_raw_text_or_path():
    assert not {"raw_text", "file_path", "doc_name"} & set(AnalyzeMinutaState.__annotations__)


async def test_no_personal_data_in_state_checkpoint_updates_trail_snapshot_or_report(seeded, settings):
    leaks, final = await _leaks(seeded, settings)
    assert "[CPF]" in final["text"] and "[NOME]" in final["text"]
    assert leaks == {k: [] for k in leaks}


async def test_the_scan_catches_the_leak_when_masking_is_switched_off(seeded, settings, monkeypatch):
    """Prova de que o teste acima mede algo: sem mascaramento, o varredor tem de acusar."""
    # Mascaramento desligado: sem regras, o texto cru sai como MaskedText e o grafo roda ate o fim.
    monkeypatch.setattr(masking, "_NAME_RULES", [])
    monkeypatch.setattr(masking, "_RULES", [])
    monkeypatch.setattr(mod, "resolve_doc_alias", lambda filename, doc_name="": masking._masked(filename))
    leaks, _ = await _leaks(seeded, settings)
    for place in ("estado", "checkpoint", "updates por no", "trilha", "relatorio"):
        assert {NAME, CPF} <= set(leaks[place]) or FILE_NAME in leaks[place], place
    assert FILE_NAME in leaks["trilha"] and FILE_NAME in leaks["relatorio"]


@pytest.mark.parametrize("bad_input", [{"raw_text": RAW, "filename": "x.txt"}, {"text": RAW, "filename": "x.txt"}])
async def test_graph_refuses_input_that_did_not_go_through_analyze(seeded, settings, monkeypatch, bad_input):
    async def boom(*a, **k):
        raise AssertionError("nenhuma chamada externa com texto cru")

    monkeypatch.setattr(mod, "call_jev", boom)
    graph = build_analyze_minuta_graph(seeded, settings)
    with pytest.raises(ValueError, match="analyze") as exc:
        await graph.ainvoke(bad_input)
    assert not _found(str(exc.value))
    assert await seeded.fetchval("SELECT count(*) FROM analyses") == 0


# ---------------------------------------------------------------- trilha


async def test_trail_is_rebuildable_from_the_analysis_id_alone(seeded, settings):
    out = await analyze(build_analyze_minuta_graph(seeded, settings), raw_text=RAW, filename=FILE_NAME)
    aid = out["analysis_id"]
    a = await seeded.fetchrow("SELECT * FROM analyses WHERE id = $1::uuid", aid)
    assert (a["status"], a["minuta_type"]) == ("done", LOCACAO) and a["finished_at"] is not None
    assert verify_snapshot(json.loads(a["rules_snapshot"]), a["rules_hash"])

    trail = await seeded.fetch("SELECT * FROM analysis_trail WHERE analysis_id = $1::uuid ORDER BY seq", aid)
    steps = [r["step"] for r in trail]
    assert steps[:3] == ["iniciar", "classificar", "ficha"] and steps[-2:] == ["analisar", "validar"]
    assert [r["seq"] for r in trail] == list(range(1, len(trail) + 1))
    assert all((r["matrix_version"], r["prompt_version"]) == (a["matrix_version"], a["prompt_version"]) for r in trail)
    assert all(r["recorded_at"] is not None for r in trail)

    ini = json.loads(trail[0]["decision"])
    assert ini["rules_hash"] == a["rules_hash"] and ini["params"]["confirm_cutoff"] == 0.5
    cls = trail[1]
    assert (cls["score"], cls["cutoff"]) == (out["score_tipo"], 0.8)
    triar = [r for r in trail if r["step"] == "triar"]
    assert [r["clause_n"] for r in triar] == [c["n"] for c in out["clausulas"]]  # um registro por clausula
    assert all(r["cutoff"] == 0.2 and r["score"] is not None for r in triar)
    excerpts = [json.loads(r["input_summary"])["excerpt"] for r in triar]
    assert all(e == c["texto"][: mod._EXCERPT] for e, c in zip(excerpts, out["clausulas"], strict=True))  # mascarado

    buscar = {r["clause_n"]: r for r in trail if r["step"] == "buscar"}
    assert set(buscar) == {c["n"] for c in out["clausulas"] if c["triado"]}
    for c in out["clausulas"]:
        if c["triado"]:
            assert buscar[c["n"]]["cited_norms"] == [n["citacao"] for n in c["normas"]]

    validar = json.loads(trail[-1]["decision"])
    alerts = out["report_envelope"]["content"]["alerts"]
    assert [x["risk_id"] for x in validar["alerts"]] == [x["risk_id"] for x in alerts] and alerts
    assert trail[-1]["cited_norms"] == sorted({n for x in alerts for n in x["legal_basis"]})


async def test_unsupported_document_trail_stops_at_validar(seeded, settings):
    out = await analyze(build_analyze_minuta_graph(seeded, settings), raw_text="ATA DE ASSEMBLEIA GERAL DE SOCIEDADE.", filename="ata.txt")
    steps = [
        r["step"]
        for r in await seeded.fetch(
            "SELECT step FROM analysis_trail WHERE analysis_id = $1::uuid ORDER BY seq", out["analysis_id"]
        )
    ]
    assert steps == ["iniciar", "classificar", "validar"]


async def test_a_failing_step_marks_the_analysis_failed_with_the_error_type_only(seeded, settings, monkeypatch):
    async def explode(*a, **k):
        raise RuntimeError(f"falhou ao processar {NAME} {CPF}")

    monkeypatch.setattr(mod, "hybrid_search_rrf", explode)
    with pytest.raises(RuntimeError):
        await analyze(build_analyze_minuta_graph(seeded, settings), raw_text=RAW, filename=FILE_NAME)
    row = await seeded.fetchrow("SELECT id, status, report, finished_at FROM analyses")
    assert row["status"] == "failed" and row["finished_at"] is not None
    assert json.loads(row["report"]) == {"error": "RuntimeError", "step": "buscar"}
    steps = [r["step"] for r in await seeded.fetch("SELECT step FROM analysis_trail WHERE analysis_id = $1 ORDER BY seq", row["id"])]
    assert steps[-1] == "triar" and "buscar" not in steps  # a trilha mostra ate onde chegou
    assert isinstance(row["id"], uuid.UUID)
