from src.config import Settings
from src.ingest.masking import (
    mask_personal_data,
    resolve_doc_alias,
    split_contract_text,
)


def test_settings_includes_typesafe_defaults():
    s = Settings(_env_file=None)
    assert s.TYPESAFE_API_KEY == ""
    assert s.TYPESAFE_BASE_URL == "https://api.typesafe.ai/v1/systemone"
    assert s.JEV_MODEL == "jev-1.14.0"


def test_mask_personal_data_masks_pii_and_preserves_contract_terms():
    raw = (
        "LOCADOR: João Carlos da Silva, brasileiro, casado, inscrito no CPF 123.456.789-00, "
        "RG nº 12.345.678-X, residente e domiciliado na Rua das Flores, 123, Centro; "
        "e-mail joao.silva@email.com.br, telefone (11) 98765-4321, CEP 01001-000, "
        "CNPJ 12.345.678/0001-99, Agência: 1234-5 Conta Corrente: 98765-0. "
        "Assina João Carlos da Silva."
    )
    masked = mask_personal_data(raw)
    assert "João Carlos da Silva" not in masked
    assert "123.456.789-00" not in masked
    assert "12.345.678-X" not in masked
    assert "Rua das Flores" not in masked
    assert "joao.silva@email.com.br" not in masked
    assert "(11) 98765-4321" not in masked
    assert "01001-000" not in masked
    assert "12.345.678/0001-99" not in masked
    assert "[NOME]" in masked
    assert "[CPF]" in masked
    assert "[RG]" in masked
    assert "[ENDERECO]" in masked
    assert "[EMAIL]" in masked
    assert "[TELEFONE]" in masked
    assert "[CEP]" in masked
    assert "[CNPJ]" in masked
    assert "[DADO_BANCARIO]" in masked
    assert "LOCADOR:" in masked


def test_resolve_doc_alias_hashes_when_doc_name_empty():
    alias = resolve_doc_alias("minuta_locacao.pdf", "")
    assert alias.startswith("documento-")
    assert alias.endswith(".pdf")
    assert len(alias) == len("documento-") + 8 + len(".pdf")
    assert resolve_doc_alias("minuta.pdf", "custom.txt") == "custom.txt"


def test_split_contract_text_respects_size_and_overlap():
    paragraphs = [f"Paragrafo {i}: " + ("x" * 280) for i in range(10)]
    text = "\n".join(paragraphs)
    chunks = split_contract_text(text, chunk_size=600, chunk_overlap=100, separator="\n")
    assert len(chunks) >= 5
    assert all(len(c) <= 600 for c in chunks)


def test_mask_longer_names_first_and_ignores_contract_terms():
    # Review Focus #4: composite names replaced before shorter ones (no "[NOME] Silva"),
    # and contractual terms are never taken as names.
    raw = (
        "LOCADOR: Ana Maria Silva, brasileira, solteira. "
        "Contrato: Maria Silva, brasileira, casada, e Silva Souza, brasileiro, casado. "
        "Ana Maria Silva assina; Maria Silva testemunha."
    )
    masked = mask_personal_data(raw)
    assert "[NOME] Silva" not in masked
    assert "Ana Maria" not in masked
    assert "LOCADOR:" in masked
    assert "Contrato" in masked
    assert mask_personal_data("CLÁUSULA Primeira, brasileira, casada") == "CLÁUSULA Primeira, brasileira, casada"
