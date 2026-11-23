"""Extracao de texto em processo separado, sem confiar no arquivo enviado."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import docx
import pytest

from src.graphs.ingest_graph import _read_path
from src.ingest.extract import (
    DocumentTimeoutError,
    InvalidDocumentError,
    UnsupportedFileError,
)
from src.ingest.isolated import extract_text_isolated
from tests.test_extract import _docx_with_table, _pdf_with_text


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
    monkeypatch.setattr(
        "src.ingest.isolated.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        ),
    )

    with pytest.raises(InvalidDocumentError):
        extract_text_isolated(".docx", b"qualquer")


def test_read_path_extracts_docx_with_table(tmp_path: Path):
    path = tmp_path / "minuta.docx"
    path.write_bytes(_docx_with_table())

    assert _read_path(path).splitlines() == [
        "Primeiro paragrafo",
        "A1 | B1",
        "A2 | B2",
        "Ultimo paragrafo",
    ]


def test_read_path_extracts_pdf(tmp_path: Path):
    path = tmp_path / "minuta.pdf"
    path.write_bytes(_pdf_with_text("Contrato de teste"))

    assert "Contrato de teste" in _read_path(path)


def test_read_path_reads_txt_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "minuta.txt"
    path.write_text("Clausula em texto puro\n", encoding="utf-8")

    def _fail(*args, **kwargs):
        raise AssertionError("extract_text_isolated should not run for .txt")

    monkeypatch.setattr("src.graphs.ingest_graph.extract_text_isolated", _fail)

    assert _read_path(path) == "Clausula em texto puro\n"
