from src.db.connection import init_db
from src.graphs.analyze_minuta_graph import build_analyze_minuta_graph
from src.graphs.ingest_graph import build_ingest_graph


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
    graph = build_analyze_minuta_graph(
        pool,
        settings,
        riscos=riscos,
        temas=["reajuste_e_indexacao"],
        tema_map={"reajuste_e_indexacao": []},
    )

    minuta = (
        "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
        "LOCADOR: Carlos Eduardo Mendes, brasileiro, CPF 999.888.777-66.\n"
        "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
        "com aluguel mensal de R$ 2.800,00.\n"
        "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M."
    )
    out = await graph.ainvoke({"raw_text": minuta, "filename": "minuta_locacao.txt"})

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
    graph = build_analyze_minuta_graph(pool, settings)

    out = await graph.ainvoke(
        {
            "raw_text": "ATA DE ASSEMBLEIA GERAL EXTRAORDINÁRIA DE SOCIEDADE ANÔNIMA FECHADA.",
            "filename": "ata_societaria.txt",
        }
    )

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
    graph = mod.build_analyze_minuta_graph(pool, settings)
    out = await graph.ainvoke({"raw_text": "ATA DE ASSEMBLEIA GERAL.", "filename": "ata.txt"})
    assert out["report_envelope"]["status"] == "unsupported"
    assert calls == ["tipo"]
