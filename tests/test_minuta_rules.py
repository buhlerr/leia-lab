from src.graphs.minuta_rules import (
    extract_ficha_candidates,
    segment_clauses,
    validate_and_format,
)


def test_extract_ficha_candidates_finds_dates_terms_and_values():
    text = (
        "O contrato inicia em 10/03/2026 pelo prazo de 30 (trinta) meses, "
        "com aluguel mensal de R$ 3.200,00 e multa de R$ 9.600,00."
    )
    cands = extract_ficha_candidates(text)
    assert [v for v, _ in cands["datas"]] == ["10/03/2026"]
    assert [v for v, _ in cands["prazos"]] == ["30 (trinta) meses"]
    assert [v for v, _ in cands["valores"]] == ["R$ 3.200,00", "R$ 9.600,00"]


def test_segment_clauses_splits_by_clausula_and_merges_short_headers():
    text = (
        "Preâmbulo curto.\n"
        "Cláusula 1ª - Do Objeto: O locador cede o imóvel residencial para moradia pelo prazo ajustado neste instrumento contratual completo.\n"
        "Cláusula 2ª - Do Aluguel e Reajuste: O aluguel mensal será reajustado mensalmente pelo IGP-M ou outro índice que vier a substituí-lo Automaticamente."
    )
    clauses = segment_clauses(text)
    assert len(clauses) == 2
    assert "Cláusula 1ª" in clauses[0]
    assert "Cláusula 2ª" in clauses[1]


def test_segment_clauses_does_not_split_inline_clause_references():
    text = (
        "CLÁUSULA 8ª – DAS GARANTIAS\n"
        "Em garantia das obrigações deste contrato, a LOCATÁRIA oferece, cumulativamente, a\n"
        "fiança prestada na Cláusula 9ª e caução em dinheiro no valor de R$ 9.400,00.\n"
        "CLÁUSULA 9ª – DA FIANÇA\n"
        "O FIADOR assume a condição de principal pagador e responsável solidário por todas as obrigações da LOCATÁRIA.\n"
    )
    clauses = segment_clauses(text)
    assert len(clauses) == 2
    assert clauses[0].startswith("CLÁUSULA 8ª")
    assert "Cláusula 9ª e caução em dinheiro" in clauses[0]
    assert clauses[1].startswith("CLÁUSULA 9ª")


def test_validate_and_format_replaces_non_literal_excerpt_and_downgrades_red_without_norm():
    cl_text = "Cláusula 4ª - O reajuste do aluguel ocorrerá a cada 6 meses pelo IGP-M."
    doc_state = {
        "filename": "minuta_teste.txt",
        "tipo": "locacao_residencial",
        "score_tipo": 0.94,
        "suportado": True,
        "ficha": {"prazo": "30 meses"},
        "ficha_confianca": {"prazo": 0.9},
        "stats": {"clausulas_total": 1, "clausulas_triadas": 1},
        "clausulas": [
            {
                "n": 1,
                "texto": cl_text,
                "risco": 0.88,
                "tema": "reajuste_e_indexacao",
                "triado": True,
                "checks": [{"id": "R-01", "risco": "Periodicidade inferior a 1 ano", "noul": 0.91}],
                "confirmados": [
                    {
                        "id": "R-01",
                        "risco": "Periodicidade inferior a 1 ano",
                        "cor": "vermelho",
                        "parte": "locatario",
                        "normas": [],
                        "noul": 0.91,
                    }
                ],
                "candidatas": [],
                "normas": [],
                "analise": {
                    "alertas": [
                        {
                            "id": "R-01",
                            "trecho": "Trecho inventado pelo modelo fora do literal",
                            "resumo": "Reajuste semestral proibido",
                            "detalhe": "A lei exige periodicidade anual.",
                            "discorda": False,
                        }
                    ]
                },
                "analise_bruta": "{}",
            }
        ],
    }

    report_md, env, diag = validate_and_format(doc_state)
    assert env["status"] == "done"
    alert = env["content"]["alerts"][0]
    assert alert["excerpt_literal"] is False
    assert alert["excerpt"] == cl_text[:240]
    assert alert["severity"] == "yellow"
    assert env["content"]["ajustes_validacao"]["trecho_nao_literal"] == 1
    assert env["content"]["ajustes_validacao"]["rebaixados_sem_norma"] == 1
    assert "[AMARELO] Reajuste semestral proibido" in report_md
    assert diag["funil"] == {"yellow": 1}


def test_validate_and_format_remarks_report_budget_skipped_clauses():
    _, env, _ = validate_and_format(
        {"filename": "m.txt", "tipo": "locacao_residencial", "suportado": True, "stats": {"sem_orcamento": 4}}
    )
    assert "4 clausulas ficaram sem redacao: o teto de custo por analise foi atingido." in env["remarks"]
    assert not any("limite" in o for o in env["remarks"])  # nao e o limite de clausulas


def test_validate_and_format_unsupported_returns_empty_alerts():
    _, env, diag = validate_and_format({"filename": "x.txt", "tipo": "nao_suportado", "suportado": False})
    assert env["status"] == "unsupported"
    assert env["content"] == {"alerts": []}
    assert diag["funil"] == {}


def test_load_risk_matrix_falls_back_to_defaults_and_reads_jsonl(tmp_path):
    import json

    from src.graphs.minuta_rules import DEFAULT_TEMAS, load_risk_matrix

    temas, riscos, tema_map = load_risk_matrix(tmp_path / "missing.jsonl")
    assert temas == DEFAULT_TEMAS and "reajuste_e_indexacao" in riscos and tema_map

    p = tmp_path / "m.jsonl"
    p.write_text(
        json.dumps({"id": "X-1", "tema": "t1", "risco": "r", "criticidade_sugerida": "amarelo",
                    "parte_prejudicada": "locador", "normas": [{"id": "n1", "citacao": "Lei X, art. 1"}]})
        + "\n",
        encoding="utf-8",
    )
    temas, riscos, tema_map = load_risk_matrix(p)
    assert temas == ["t1"] and riscos["t1"][0]["normas"][0]["citacao"] == "Lei X, art. 1"
    assert tema_map == {"t1": ["n1"]}
