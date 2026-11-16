"""Extracao de texto em processo separado, sem confiar no arquivo enviado."""

from __future__ import annotations

import io
import subprocess

import docx
import pytest

from src.ingest.extract import (
    DocumentTooLargeError,
    InvalidDocumentError,
    UnsupportedFileError,
)
from src.ingest.isolated import extract_text_isolated


def _docx_with_text(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extract_isolated_reads_a_docx_in_a_separate_process():
    text = extract_text_isolated("minuta.docx", _docx_with_text("Clausula primeira"))

    assert "Clausula primeira" in text


def test_extract_isolated_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileError):
        extract_text_isolated("minuta.txt", b"texto qualquer")


def test_extract_isolated_reports_a_timeout_as_too_large(monkeypatch: pytest.MonkeyPatch):
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr("src.ingest.isolated.subprocess.run", _timeout)

    with pytest.raises(DocumentTooLargeError):
        extract_text_isolated("minuta.docx", b"qualquer")


def test_extract_isolated_rejects_a_failed_process(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "src.ingest.isolated.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        ),
    )

    with pytest.raises(InvalidDocumentError):
        extract_text_isolated("minuta.docx", b"qualquer")
