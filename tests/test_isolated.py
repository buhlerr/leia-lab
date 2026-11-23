"""Extracao de texto em processo separado, sem confiar no arquivo enviado."""

from __future__ import annotations

import hashlib
import io
import subprocess
from pathlib import Path

import docx
import pytest

from src.graphs.ingest_graph import prepare_ingest_input
from src.ingest.extract import (
    DocumentTimeoutError,
    InvalidDocumentError,
    UnsupportedFileError,
)
from src.ingest.isolated import extract_text_isolated
from tests.test_extract import _docx_with_table, _pdf_with_text

# Dado pessoal de mentira no nome do arquivo e no corpo: a extracao devolve texto MASCARADO
# e um apelido que nao carrega nada disso.
NAME = "Carlos Eduardo Mendes"
CPF = "999.888.777-66"


def _alias(path: Path) -> str:
    """O apelido exato que resolve_doc_alias deve devolver para ``path``: documento-<sha8>.<ext>."""
    return f"documento-{hashlib.sha256(path.name.encode('utf-8')).hexdigest()[:8]}{path.suffix}"


def _docx_with_text(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extract_isolated_reads_a_docx_in_a_separate_process():
    text = extract_text_isolated(".docx", _docx_with_text("Clausula primeira"))

    assert "Clausula primeira" in text


def test_extract_isolated_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileError):
        extract_text_isolated(".txt", b"texto qualquer")


def test_extract_isolated_reports_a_timeout_as_a_timeout():
    with pytest.raises(DocumentTimeoutError):
        extract_text_isolated(".docx", _docx_with_text("Clausula primeira"), timeout_s=0.001)


def test_extract_isolated_refuses_a_real_filename():
    with pytest.raises(ValueError, match="extensao"):
        extract_text_isolated("contrato-joao-da-silva.docx", _docx_with_text("Clausula primeira"))


def test_extract_isolated_rejects_a_failed_process(monkeypatch: pytest.MonkeyPatch):
    # Nao existe byte que derrube o worker de verdade: todo erro de leitura e
    # normalizado em DocumentError DENTRO de extract_by_extension, o worker sai
    # com 0 e um JSON de erro. Codigo de saida != 0 so acontece se o processo
    # morre (OOM kill, sinal) -- caminho sem entrada deterministica, simulado.
    monkeypatch.setattr(
        "src.ingest.isolated.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        ),
    )

    with pytest.raises(InvalidDocumentError):
        extract_text_isolated(".docx", b"qualquer")


async def test_prepare_ingest_input_extracts_docx_with_table(tmp_path: Path):
    path = tmp_path / f"minuta_{NAME}_{CPF}.docx"
    path.write_bytes(_docx_with_table())

    state = await prepare_ingest_input(file_path=path)

    assert state["masked_text"].splitlines() == [
        "Primeiro paragrafo",
        "A1 | B1",
        "A2 | B2",
        "Ultimo paragrafo",
    ]
    # O nome real do arquivo (com PII) nao entra no estado: vira o apelido publico exato.
    assert state["resolved_filename"] == _alias(path)


async def test_prepare_ingest_input_extracts_pdf_and_masks(tmp_path: Path):
    path = tmp_path / f"minuta_{NAME}_{CPF}.pdf"
    path.write_bytes(_pdf_with_text(f"LOCADOR: {NAME}, brasileiro, CPF {CPF}."))

    state = await prepare_ingest_input(file_path=path)

    # A extracao devolve o texto MASCARADO: nada do dado pessoal cru atravessa.
    assert CPF not in state["masked_text"]
    assert "[CPF]" in state["masked_text"]
    assert state["resolved_filename"] == _alias(path)


async def test_prepare_ingest_input_reads_txt_and_masks(tmp_path: Path):
    path = tmp_path / f"minuta_{NAME}_{CPF}.txt"
    path.write_text(f"LOCADOR: {NAME}, CPF {CPF}.\n", encoding="utf-8")

    state = await prepare_ingest_input(file_path=path)

    assert CPF not in state["masked_text"]
    assert "[CPF]" in state["masked_text"]
    assert state["resolved_filename"] == _alias(path)
