from src.db.connection import init_db
from src.db.seed import seed_defaults
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph
from src.graphs.ingest_graph import build_ingest_graph
from tests._rules_helper import use_rules


async def test_analyze_minuta_graph_end_to_end_supported_contract(pool, settings):
    await init_db(pool)
    ingest = build_ingest_graph(pool, settings)
    await ingest.ainvoke(
        {
            "raw_text": "Lei 10.192/2001, art. 2º - É nula de pleno direito a estipulação de reajuste em periodicidade inferior a um ano.",
            "filename": "lei-10192-2001-art-2.txt",
            "doc_name": "Lei 10.192/2001, art. 2º",
        }
    )

    riscos = {
        "reajuste_e_indexacao": [
            {
                "id": "REAJ-01",
                "risco": "Reajuste em periodicidade inferior a 12 meses",
                "cor": "vermelho",
                "parte": "locatario",
                "normas": [{"id": "lei-10192-2001-art-2", "citacao": "Lei 10.192/2001, art. 2º"}],
            }
        ]
    }
    await use_rules(pool, riscos, ["reajuste_e_indexacao"])
    graph = build_analyze_minuta_graph(pool, settings)

    minuta = (
        "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
        "LOCADOR: Carlos Eduardo Mendes, brasileiro, CPF 999.888.777-66.\n"
        "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
        "com aluguel mensal de R$ 2.800,00.\n"
        "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M."
    )
    out = await analyze(graph, raw_text=minuta, filename="minuta_locacao.txt")

    assert "999.888.777-66" not in out["text"]
    assert out["suportado"] is True
    assert out["tipo"] == "locacao_residencial"
    assert out["ficha"]["data_inicio"] == "01/04/2026"
    assert out["ficha"]["prazo"] == "30 meses"
    assert out["ficha"]["valor_aluguel"] == "R$ 2.800,00"
    assert out["report_envelope"]["status"] == "done"
    alerts = out["report_envelope"]["content"]["alerts"]
    assert len(alerts) >= 1
    assert alerts[0]["risk_id"] == "REAJ-01"
    assert alerts[0]["severity"] == "red"
    assert alerts[0]["legal_basis"] == ["Lei 10.192/2001, art. 2º"]
    assert "```json" in out["report_text"]
    assert out["diagnostics"]["minuta_id"].startswith("documento-")


async def test_analyze_minuta_graph_short_circuits_unsupported_doc(pool, settings):
    await init_db(pool)
    await seed_defaults(pool)
    graph = build_analyze_minuta_graph(pool, settings)

    out = await analyze(graph, raw_text="ATA DE ASSEMBLEIA GERAL EXTRAORDINÁRIA DE SOCIEDADE ANÔNIMA FECHADA.", filename="ata_societaria.txt")

    assert out["suportado"] is False
    assert "ficha" not in out or out.get("ficha") is None
    assert out["report_envelope"]["status"] == "unsupported"
    assert out["report_envelope"]["content"]["alerts"] == []
    assert "Tipo de minuta nao suportado" in out["report_text"]


async def test_unsupported_doc_never_calls_ficha_triar_buscar_analisar(pool, settings, monkeypatch):
    # Review Focus #1: the conditional edge jumps classificar -> validar.
    import src.graphs.analyze_minuta_graph as mod

    calls: list[str] = []
    real = mod.call_jev

    async def spy(state, questions, settings=None):
        calls.append(",".join(sorted(questions)))
        return await real(state, questions, settings)

    monkeypatch.setattr(mod, "call_jev", spy)

    async def boom(*a, **k):
        raise AssertionError("must not be called for unsupported docs")

    monkeypatch.setattr(mod, "chat_completion", boom)
    monkeypatch.setattr(mod, "hybrid_search_rrf", boom)

    await init_db(pool)
    await seed_defaults(pool)
    graph = mod.build_analyze_minuta_graph(pool, settings)
    out = await analyze(graph, raw_text="ATA DE ASSEMBLEIA GERAL.", filename="ata.txt")
    assert out["report_envelope"]["status"] == "unsupported"
    assert calls == ["tipo"]


_MINUTA = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00 e demais encargos ajustados entre as partes.\n"
    "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M, "
    "conforme ajustado entre as partes neste instrumento contratual."
)
_RISCOS = {
    "reajuste_e_indexacao": [
        {
            "id": "REAJ-01",
            "risco": "Reajuste em periodicidade inferior a 12 meses",
            "cor": "vermelho",
            "parte": "locatario",
            "normas": [{"id": "lei-10192-2001-art-2", "citacao": "Lei 10.192/2001, art. 2º"}],
        }
    ]
}


async def test_triage_cutoff_gates_risk_checks(pool, settings, monkeypatch):
    # Clauses below triage_cutoff must not reach the per-risk Jev check nor produce alerts.
    import src.graphs.analyze_minuta_graph as mod
    from src.clients.jev import call_jev as real

    asked: list[set[str]] = []

    async def spy(state, questions, settings=None):
        asked.append(set(questions))
        res = await real(state, questions, settings)
        if "risco" in questions:
            res["answers"]["risco"]["noul"] = 0.05
        return res

    monkeypatch.setattr(mod, "call_jev", spy)
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    graph = mod.build_analyze_minuta_graph(pool, settings)
    out = await analyze(graph, raw_text=_MINUTA, filename="minuta.txt")

    assert not any("REAJ-01" in q for q in asked)
    assert all(cl["checks"] == [] and cl["confirmados"] == [] for cl in out["clausulas"])
    assert out["report_envelope"]["content"]["alerts"] == []


async def test_jev_concurrency_is_capped_across_nested_fanouts(pool, settings, monkeypatch):
    import asyncio

    import src.graphs.analyze_minuta_graph as mod
    from src.clients.jev import call_jev as real

    inflight = 0
    peak = 0

    async def spy(state, questions, settings=None):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.005)
        try:
            return await real(state, questions, settings)
        finally:
            inflight -= 1

    monkeypatch.setattr(mod, "call_jev", spy)
    await init_db(pool)
    ingest = build_ingest_graph(pool, settings)
    for i in range(6):
        await ingest.ainvoke({"raw_text": f"Norma {i}: reajuste do aluguel e prazo.", "filename": f"n{i}.txt", "doc_name": f"Norma {i}"})
    clausulas = "\n".join(
        f"Cláusula {i}ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M, "
        "conforme ajustado entre as partes neste instrumento contratual de locação residencial."
        for i in range(1, 13)
    )
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    graph = mod.build_analyze_minuta_graph(pool, settings)
    await analyze(graph, raw_text="CONTRATO DE LOCAÇÃO RESIDENCIAL\n" + clausulas, filename="m.txt")

    assert 1 < peak <= mod._CONCURRENCY


async def test_tema_map_ids_resolve_to_citation_without_duplicates_or_empty_norms(pool, settings):
    await init_db(pool)
    ingest = build_ingest_graph(pool, settings)
    await ingest.ainvoke(
        {
            "raw_text": "Lei 10.192/2001, art. 2º - É nula a estipulação de reajuste inferior a um ano.",
            "filename": "lei.txt",
            "doc_name": "Lei 10.192/2001, art. 2º",
        }
    )
    await use_rules(
        pool,
        _RISCOS,
        ["reajuste_e_indexacao"],
        # id known to the matrix, plus one id/citation absent from the KB.
        {"reajuste_e_indexacao": ["lei-10192-2001-art-2", "lei-9999-inexistente"]},
    )
    graph = build_analyze_minuta_graph(pool, settings)
    out = await analyze(graph, raw_text=_MINUTA, filename="minuta.txt")

    for cl in out["clausulas"]:
        citacoes = [n["citacao"] for n in cl["normas"]]
        assert len(citacoes) == len(set(citacoes))  # id and citation are one key
        assert all(n["texto"] for n in cl["normas"])  # no empty-text norm reaches the writer
        assert "lei-10192-2001-art-2" not in citacoes and "lei-9999-inexistente" not in citacoes
    assert any(n["citacao"] == "Lei 10.192/2001, art. 2º" for cl in out["clausulas"] for n in cl["normas"])
