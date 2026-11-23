import copy
import pickle

import pytest

from src.config import Settings
from src.ingest.masking import (
    MaskedText,
    UnmaskedTextError,
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
    chunks = split_contract_text(mask_personal_data(text), chunk_size=600, chunk_overlap=100, separator="\n")
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


def test_masked_text_is_created_only_by_the_masking_module():
    with pytest.raises(TypeError, match="mask_personal_data"):
        MaskedText("LOCADOR: Ana Maria Silva")
    masked = mask_personal_data("LOCADOR: Ana Maria Silva, brasileira")
    assert isinstance(masked, MaskedText) and mask_personal_data(masked) is masked
    assert isinstance(resolve_doc_alias("minuta_Ana.pdf"), MaskedText)
    assert type(masked[:5]) is str and type(masked + "x") is str  # derivado volta a ser texto comum
    assert pickle.loads(pickle.dumps(masked)) == masked and isinstance(copy.deepcopy(masked), MaskedText)


def test_split_refuses_unmasked_text_and_keeps_chunks_masked():
    with pytest.raises(UnmaskedTextError, match="split_contract_text"):
        split_contract_text("Paragrafo 1\nParagrafo 2")
    chunks = split_contract_text(mask_personal_data("Paragrafo 1\nParagrafo 2"), chunk_size=12, chunk_overlap=0)
    assert chunks == ["Paragrafo 1", "Paragrafo 2"] and all(isinstance(c, MaskedText) for c in chunks)


@pytest.mark.parametrize(
    "rotulo",
    [
        "LOCADOR", "Locadora", "LOCATÁRIO", "Locataria", "FIADORA", "Cônjuge", "Testemunha 2", "Nome completo",
        "CONTRATANTE", "Contratante", "CONTRATADA", "CONTRATADO", "CONTRATANTES", "LOCADOR(A)", "OUTORGANTE",
        "OUTORGADA", "INTERVENIENTE", "ANUENTE", "PROCURADOR", "CONTRATANTE(S)", "LOCADOR(A)S", "LOCADOR(A)(S)",
        "LOCADOR/A", "LOCADOR (A)", "RESPONSÁVEIS", "REPRESENTANTES LEGAIS",
    ],
)
def test_name_after_any_party_label_is_masked_everywhere(rotulo):
    raw = f"{rotulo}: Helena Ribeiro Prates, residente nesta cidade. Assina Helena Ribeiro Prates."
    masked = mask_personal_data(raw)
    assert "Helena" not in masked and "Prates" not in masked
    assert masked.count("[NOME]") == 2
    assert masked.startswith(f"{rotulo}:")


@pytest.mark.parametrize(
    "rotulo", ["o LOCADOR", "a Locadora", "a CONTRATANTE", "os LOCADORES", "Os LOCADORES", "A LOCADORA"]
)
def test_party_label_before_a_qualified_name_does_not_shield_it(rotulo):
    masked = mask_personal_data(f"{rotulo} Helena Ribeiro Prates, brasileira, casada. Assina Helena Ribeiro Prates.")
    assert masked == f"{rotulo} [NOME], brasileira, casada. Assina [NOME]."


def test_party_labels_alone_are_not_names():
    raw = "LOCADOR E LOCATÁRIO, brasileiros, ajustam; CONTRATANTE: LOCADORA E LOCATÁRIA Assinam."
    assert mask_personal_data(raw) == raw


@pytest.mark.parametrize("rotulo", ["FIADOR DE", "CÔNJUGE DE", "PROCURADOR DE", "REPRESENTANTE LEGAL DE"])
def test_preposition_after_a_party_label_is_not_part_of_the_name(rotulo):
    masked = mask_personal_data(f"{rotulo} Helena Ribeiro Prates, brasileira, casada. Assina Helena Ribeiro Prates.")
    assert masked == f"{rotulo} [NOME], brasileira, casada. Assina [NOME]."


@pytest.mark.parametrize(
    "raw",
    [
        "LOCADOR DO IMÓVEL, brasileiro, entrega a posse do imóvel e a vistoria do imóvel.",
        "LOCADOR DO IMÓVEL, inscrito no CPF, entrega a posse do imóvel e a vistoria do imóvel.",
        "CONTRATANTE: REPRESENTANTE DA EMPRESA. Os dados da empresa seguem abaixo.",
        "CLÁUSULA 5: O LOCADOR DEVE INFORMAR CPF. O locatário deve informar o banco.",
    ],
)
def test_legal_phrases_after_a_party_label_are_not_names(raw):
    assert mask_personal_data(raw) == raw


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("a LOCADORA Helena, brasileira, casada.", "a LOCADORA [NOME], brasileira, casada."),
        ("o PROCURADOR Mendes, CPF 123.456.789-00.", "o PROCURADOR [NOME], CPF [CPF]."),
        ("Sra. Locadora Helena recebeu as chaves.", "Sra. Locadora [NOME] recebeu as chaves."),
        ("LOCADOR: Cônjuge Maria.", "LOCADOR: Cônjuge [NOME]."),
    ],
)
def test_single_name_after_a_party_label_is_masked_where_it_was_found(raw, esperado):
    assert mask_personal_data(raw) == esperado
