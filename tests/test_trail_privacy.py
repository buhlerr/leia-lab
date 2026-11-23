"""M2b: trilha reconstruivel pelo analysis_id e nenhum dado pessoal fora da maquina local."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import aclosing

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import src.graphs.analyze_minuta_graph as mod
from src.db.connection import init_db
from src.db.defaults import LOCACAO_RESIDENCIAL as LOCACAO
from src.db.rules import verify_snapshot
from src.db.seed import seed_defaults
from src.db.analyses import append_trail, finish_analysis
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
    final = (await graph.compiled.aget_state(cfg)).values
    checkpoints = [s async for s in graph.compiled.aget_state_history(cfg)]
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


@pytest.mark.parametrize(
    "bad_input",
    [
        {"raw_text": RAW, "filename": "x.txt"},
        {"text": RAW, "filename": "x.txt"},
        {"text": "CONTRATO DE LOCACAO RESIDENCIAL", "filename": "x.txt"},  # mascarado, mas sem analysis_id
    ],
)
async def test_graph_refuses_input_that_did_not_go_through_analyze(seeded, settings, monkeypatch, bad_input):
    async def boom(*a, **k):
        raise AssertionError("nenhuma chamada externa com texto cru")

    monkeypatch.setattr(mod, "call_jev", boom)
    graph = build_analyze_minuta_graph(seeded, settings)
    with pytest.raises(ValueError, match="analyze") as exc:
        await graph.compiled.ainvoke(bad_input)
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
    assert json.loads(row["report"]) == {"error": "RuntimeError"}
    steps = [r["step"] for r in await seeded.fetch("SELECT step FROM analysis_trail WHERE analysis_id = $1 ORDER BY seq", row["id"])]
    assert steps[-1] == "triar" and "buscar" not in steps  # a trilha mostra ate onde chegou
    assert isinstance(row["id"], uuid.UUID)


async def _only_analysis(pool) -> tuple[dict, list[str]]:
    row = await pool.fetchrow("SELECT id, status, report, finished_at FROM analyses")
    steps = [r["step"] for r in await pool.fetch("SELECT step FROM analysis_trail WHERE analysis_id = $1 ORDER BY seq", row["id"])]
    return {**row, "report": json.loads(row["report"]) if row["report"] else None}, steps


async def test_a_failure_right_after_the_insert_marks_the_analysis_failed(seeded, settings, monkeypatch):
    """PR #31: a linha ja existe, mas o estado do grafo ainda nao tem o analysis_id."""

    def explode(analysis_id):
        raise RuntimeError(f"rastreio caiu com {NAME}")

    monkeypatch.setattr(mod, "tag_analysis", explode)
    with pytest.raises(RuntimeError):
        await analyze(build_analyze_minuta_graph(seeded, settings), raw_text=RAW, filename=FILE_NAME)
    row, steps = await _only_analysis(seeded)
    assert (row["status"], row["report"], steps) == ("failed", {"error": "RuntimeError"}, ["iniciar"])
    assert row["finished_at"] is not None


async def test_a_cancelled_analysis_ends_failed(seeded, settings, monkeypatch):
    """Cliente que desconecta ou timeout: o CancelledError nao e Exception e nao pode deixar 'running'."""
    calling = asyncio.Event()

    async def hang(*a, **k):
        calling.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "call_jev", hang)
    run = asyncio.create_task(analyze(build_analyze_minuta_graph(seeded, settings), raw_text=RAW, filename=FILE_NAME))
    await calling.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    row, steps = await _only_analysis(seeded)
    assert (row["status"], row["report"], steps) == ("failed", {"error": "CancelledError"}, ["iniciar"])
    assert row["finished_at"] is not None


async def test_a_second_cancel_during_the_failure_write_still_ends_the_row_failed(seeded, settings, monkeypatch):
    """2o cancelamento durante a escrita de falha: analyze() so termina DEPOIS da linha virar 'failed'."""
    handler_started = asyncio.Event()
    real_fail = mod.fail_analysis

    async def slow_fail(pool, analysis_id, error):
        handler_started.set()
        await asyncio.sleep(0.05)  # janela em que o 2o cancelamento chega durante a escrita
        await real_fail(pool, analysis_id, error)

    monkeypatch.setattr(mod, "fail_analysis", slow_fail)
    calling = asyncio.Event()

    async def hang(*a, **k):
        calling.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "call_jev", hang)
    run = asyncio.create_task(analyze(build_analyze_minuta_graph(seeded, settings), raw_text=RAW, filename=FILE_NAME))
    await calling.wait()
    run.cancel()
    await handler_started.wait()  # a escrita de falha comecou: o 2o cancelamento chega AQUI
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    row, steps = await _only_analysis(seeded)
    assert (row["status"], row["report"], steps) == ("failed", {"error": "CancelledError"}, ["iniciar"])
    assert row["finished_at"] is not None


async def test_a_failure_write_that_never_returns_releases_the_request(seeded, settings, monkeypatch, caplog):
    """Banco travado na escrita de falha: o pedido termina com aviso, em vez de pendurar para sempre."""
    handler_started = asyncio.Event()

    async def stuck_fail(pool, analysis_id, error):
        handler_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "fail_analysis", stuck_fail)
    monkeypatch.setattr(mod, "_FAILURE_WRITE_TIMEOUT", 0.05)
    calling = asyncio.Event()

    async def hang(*a, **k):
        calling.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "call_jev", hang)
    run = asyncio.create_task(analyze(build_analyze_minuta_graph(seeded, settings), raw_text=RAW, filename=FILE_NAME))
    await calling.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):  # sem o teto, este await pendurava para sempre
        await asyncio.wait_for(run, timeout=2)
    assert handler_started.is_set()
    assert "a escrita de falha nao terminou" in caplog.text


async def test_a_stream_consumer_that_stops_early_closes_the_row(seeded, settings, monkeypatch):
    """Quem consome analyze_stream para antes do fim e fecha o iterador: a linha termina 'failed'."""
    graph = build_analyze_minuta_graph(seeded, settings)
    async with aclosing(analyze_stream(graph, raw_text=RAW, filename=FILE_NAME)) as stream:
        async for _update in stream:
            break  # consumidor satisfeito com o primeiro update: a analise NAO terminou
    row, steps = await _only_analysis(seeded)
    assert (row["status"], row["report"], steps) == ("failed", {"error": "GeneratorExit"}, ["iniciar"])
    assert row["finished_at"] is not None


# ---------------------------------------------------------------- a escrita ao banco e fail-safe


async def test_a_trail_step_that_carries_raw_text_is_masked_at_the_write(seeded):
    """Revisao do PR #42 (achado proprio): um passo malcomportado que monte texto cru
    nao chega cru ao analysis_trail -- a escrita mascara na fronteira do banco."""
    aid = str(uuid.uuid4())
    await seeded.execute(
        "INSERT INTO analyses (id, filename_alias, text_sha256, rules_snapshot, rules_hash, matrix_version, "
        "prompt_version, domain_history_id) VALUES ($1::uuid, 'documento-x.txt', 'h', '{}'::jsonb, 'rh', 'mv', 'pv', 0)",
        aid,
    )
    await append_trail(
        seeded,
        aid,
        {"matrix_version": "v", "prompt_version": "p"},
        [
            {
                "step": "triar",
                "clause_n": 1,
                "input_summary": {"excerpt": f"LOCADOR: {NAME}, CPF {CPF}."},
                "decision": {"observacao": f"e-mail {EMAIL} citado no corpo"},
            }
        ],
    )
    written = await seeded.fetchrow("SELECT input_summary::text AS i, decision::text AS d FROM analysis_trail")
    blob = written["i"] + written["d"]
    assert [s for s in (NAME, CPF, EMAIL, "99988877766") if s in blob] == []  # nada cru no banco
    assert "[CPF]" in blob and "[EMAIL]" in blob


async def test_a_report_that_carries_raw_text_is_masked_at_the_write(seeded):
    """O mesmo fail-safe vale para o relatorio gravado em analyses."""
    aid = str(uuid.uuid4())
    await seeded.execute(
        "INSERT INTO analyses (id, filename_alias, text_sha256, rules_snapshot, rules_hash, matrix_version, "
        "prompt_version, domain_history_id) VALUES ($1::uuid, 'documento-x.txt', 'h', '{}'::jsonb, 'rh', 'mv', 'pv', 0)",
        aid,
    )
    await finish_analysis(
        seeded,
        aid,
        status="done",
        minuta_type=None,
        report={"content": {"alerts": [{"trecho": f"LOCADOR: {NAME}, CPF {CPF}."}]}},
    )
    report = (await seeded.fetchrow("SELECT report::text AS r FROM analyses WHERE id = $1::uuid", aid))["r"]
    assert [s for s in (NAME, CPF, "99988877766") if s in report] == []
    assert "[CPF]" in report
