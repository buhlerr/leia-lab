"""Text extraction for draft documents uploaded as PDF or DOCX.

The format is chosen from ``filename``'s extension, case-insensitively. Read
failures are normalized into :class:`DocumentError` subclasses so callers can
distinguish unsupported formats, unreadable files and documents with no text
(for example scanned PDFs) without inspecting library-specific exceptions.
"""

from __future__ import annotations

import io
import os
import zipfile

import docx
import pypdf
from docx.text.paragraph import Paragraph
from pypdf import apply_configuration

# Os limites valem antes de qualquer biblioteca abrir o arquivo: um zip pequeno
# pode inflar para gigabytes e esgotar a memoria da maquina.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
# Mesmo teto do pipeline: nao adianta extrair texto que seria recusado depois.
MAX_TEXT_CHARS = 200_000
# Limitam a memoria de um PDF com muitas streams infladas.
MAX_PDF_PAGES = 500
MAX_PDF_STREAM_BYTES = 8_000_000


DOCUMENT_ERRORS: dict[str, type[DocumentError]] = {}


class DocumentError(ValueError):
    """Base class for failures while reading a draft document.

    Each subclass declares the HTTP contract the API answers with, so a new
    failure cannot exist without one. ``public_message`` never echoes the document.
    """

    http_status: int
    code: str
    public_message: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        missing = [a for a in ("http_status", "code", "public_message") if a not in cls.__dict__]
        if missing:
            raise TypeError(f"{cls.__name__} must declare {', '.join(missing)} (its HTTP contract in the API)")
        DOCUMENT_ERRORS[cls.__name__] = cls


class UnsupportedFileError(DocumentError):
    """Raised when ``filename`` has an extension this module cannot read."""

    http_status = 415
    code = "unsupported_file"
    public_message = "Formato de arquivo nao suportado; envie .pdf, .docx ou .txt."


class InvalidDocumentError(DocumentError):
    """Raised when the file is corrupted or cannot be read by its library."""

    http_status = 422
    code = "invalid_document"
    public_message = "O documento enviado nao pode ser lido."


class EmptyDocumentError(DocumentError):
    """Raised when the document yields no text (for example a scanned PDF)."""

    http_status = 422
    code = "empty_document"
    public_message = "O documento enviado nao contem texto extraivel."


class DocumentTooLargeError(DocumentError):
    """Raised when reading the file would exceed the size limits."""

    http_status = 413
    code = "document_too_large"
    public_message = "O arquivo excede o limite de tamanho permitido."


class DocumentTimeoutError(DocumentError):
    """Raised when the isolated reader does not finish within its time limit."""

    http_status = 422
    code = "document_timeout"
    public_message = "O documento demorou demais para ser lido."


def _extract_pdf(data: bytes) -> str:
    """Return the text of every PDF page, joining pages with a blank line."""
    with apply_configuration(zlib_maximum_output_length=MAX_PDF_STREAM_BYTES):
        reader = pypdf.PdfReader(io.BytesIO(data))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentTooLargeError(
                f"The document has more than {MAX_PDF_PAGES} pages"
            )
        pages: list[str] = []
        total = 0
        for page in reader.pages:
            extracted = page.extract_text() or ""
            total += len(extracted)
            if total > MAX_TEXT_CHARS:
                raise DocumentTooLargeError(
                    f"The document has more than {MAX_TEXT_CHARS} characters of text"
                )
            pages.append(extracted)
        return "\n\n".join(pages)


def _check_docx_uncompressed(data: bytes) -> None:
    """Sums the declared entry sizes before python-docx expands them in memory."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = sum(entry.file_size for entry in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise InvalidDocumentError("Could not read the document") from exc
    if total > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise DocumentTooLargeError(
            f"The document expands to more than {MAX_DOCX_UNCOMPRESSED_BYTES} bytes"
        )


def _extract_docx(data: bytes) -> str:
    """Return paragraphs and table rows in their original document order.

    Each table row becomes one line with its cell texts joined by ``" | "``.
    """
    document = docx.Document(io.BytesIO(data))
    blocks: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            blocks.append(block.text)
        else:
            for row in block.rows:
                blocks.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(blocks)


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from ``data`` according to ``filename``'s extension."""
    return extract_by_extension(os.path.splitext(filename)[1], data)


def extract_by_extension(extension: str, data: bytes) -> str:
    """Extract plain text from ``data`` read as ``extension`` (``.pdf`` or ``.docx``).

    The result is stripped; an empty result raises :class:`EmptyDocumentError`.
    Error messages never include document contents.
    """
    extension = extension.lower()

    if extension == ".pdf":
        extractor = _extract_pdf
    elif extension == ".docx":
        extractor = _extract_docx
    else:
        raise UnsupportedFileError(f"Unsupported file extension: {extension or '<none>'}")

    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentTooLargeError(f"The file is larger than {MAX_UPLOAD_BYTES} bytes")
    if extension == ".docx":
        _check_docx_uncompressed(data)

    try:
        text = extractor(data)
    except DocumentError:
        raise
    except Exception as exc:
        raise InvalidDocumentError("Could not read the document") from exc

    text = text.strip()
    if not text:
        raise EmptyDocumentError("The document contains no extractable text")
    return text
