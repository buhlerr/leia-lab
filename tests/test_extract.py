"""Extracao de texto de minutas enviadas como arquivo PDF ou DOCX."""

from __future__ import annotations

import io
import zipfile

import docx
import pypdf
import pytest

from src.ingest.extract import (
    DocumentTooLargeError,
    EmptyDocumentError,
    InvalidDocumentError,
    UnsupportedFileError,
    extract_text,
)


def _docx_with_table() -> bytes:
    document = docx.Document()
    document.add_paragraph("Primeiro paragrafo")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A1"
    table.cell(0, 1).text = "B1"
    table.cell(1, 0).text = "A2"
    table.cell(1, 1).text = "B2"
    document.add_paragraph("Ultimo paragrafo")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def test_extract_docx_keeps_document_order():
    text = extract_text("minuta.docx", _docx_with_table())

    assert text.splitlines() == [
        "Primeiro paragrafo",
        "A1 | B1",
        "A2 | B2",
        "Ultimo paragrafo",
    ]


def test_extract_pdf_accepts_uppercase_extension():
    text = extract_text("minuta.PDF", _pdf_with_text("Contrato de teste"))

    assert "Contrato de teste" in text


def test_extract_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileError):
        extract_text("minuta.txt", b"texto qualquer")


def test_extract_invalid_pdf_raises():
    with pytest.raises(InvalidDocumentError):
        extract_text("minuta.pdf", b"isto nao e um pdf")


def test_extract_invalid_docx_raises():
    with pytest.raises(InvalidDocumentError):
        extract_text("minuta.docx", b"isto nao e um docx")


def test_extract_blank_pdf_raises_empty_document_error():
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(EmptyDocumentError):
        extract_text("escaneado.pdf", buffer.getvalue())


def test_extract_rejects_upload_above_the_size_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.ingest.extract.MAX_UPLOAD_BYTES", 10)

    with pytest.raises(DocumentTooLargeError):
        extract_text("minuta.pdf", b"x" * 11)


def test_extract_rejects_docx_that_would_inflate_beyond_the_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"\0" * 100_000)
    monkeypatch.setattr("src.ingest.extract.MAX_DOCX_UNCOMPRESSED_BYTES", 1_000)

    with pytest.raises(DocumentTooLargeError):
        extract_text("minuta.docx", buffer.getvalue())


def test_extract_stops_pdf_reading_when_text_passes_the_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("src.ingest.extract.MAX_TEXT_CHARS", 5)

    with pytest.raises(DocumentTooLargeError):
        extract_text("minuta.pdf", _pdf_with_text("Contrato de teste"))


def test_extract_rejects_pdf_above_the_page_limit(monkeypatch: pytest.MonkeyPatch):
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    monkeypatch.setattr("src.ingest.extract.MAX_PDF_PAGES", 2)

    with pytest.raises(DocumentTooLargeError):
        extract_text("minuta.pdf", buffer.getvalue())
