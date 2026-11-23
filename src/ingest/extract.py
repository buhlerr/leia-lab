"""Text extraction for draft documents (PDF, DOCX and plain text).

All callers go through :func:`extract`, which enforces byte and character limits
and returns :class:`BoundedText`. Read failures are normalized into
:class:`DocumentError` subclasses so callers can distinguish unsupported formats,
unreadable files and documents with no text without inspecting library-specific
exceptions.
"""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

_BINARY_EXTENSIONS = frozenset({".pdf", ".docx"})
DEFAULT_TEXT_EXTENSIONS = frozenset({".txt"})
_KEY = object()


class BoundedText(str):
    """Texto extraido com tamanho ja verificado (``<= MAX_TEXT_CHARS``).

    So este modulo cria instancias; fatiar ou concatenar devolve ``str`` comum.
    """

    __slots__ = ()

    def __new__(cls, value: str, *, _key: object = None) -> BoundedText:
        if _key is not _KEY:
            raise TypeError("BoundedText is created only by src.ingest.extract; pass input through extract()")
        return super().__new__(cls, value)

    def __reduce__(self) -> tuple[Any, ...]:
        return (_bounded, (str(self),))


def _bounded(value: str) -> BoundedText:
    return BoundedText(value, _key=_KEY)


def require_bounded(value: object, *, what: str) -> BoundedText:
    """Recusa qualquer valor que nao seja ``BoundedText``."""
    if isinstance(value, BoundedText):
        return value
    raise TypeError(f"{what} requires BoundedText; pass input through src.ingest.extract.extract()")


DOCUMENT_ERRORS: dict[str, type[DocumentError]] = {}


class DocumentError(ValueError):
    """Base class for failures while reading a draft document.

    Each subclass declares the HTTP contract the API answers with, so a new
    failure cannot exist without one, and two failures cannot share a ``code``.
    ``public_message`` never echoes the document.
    """

    http_status = 422
    code = "invalid_document"
    public_message = "O documento enviado nao pode ser lido."

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        missing = [a for a in ("http_status", "code", "public_message") if not cls.__dict__.get(a)]
        if missing:
            raise TypeError(f"{cls.__name__} must declare {', '.join(missing)} (its HTTP contract in the API)")
        taken = {c.code: name for name, c in DOCUMENT_ERRORS.items() if name != cls.__name__}
        if cls.code in taken or cls.__name__ in DOCUMENT_ERRORS:
            raise TypeError(f"{cls.__name__}: code {cls.code!r} or name already used by {taken.get(cls.code, cls.__name__)}")
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
    total = 0
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            lines = [block.text]
        else:
            lines = [" | ".join(cell.text for cell in row.cells) for row in block.rows]
        for line in lines:
            total += len(line)
            if total > MAX_TEXT_CHARS:
                raise DocumentTooLargeError(
                    f"The document has more than {MAX_TEXT_CHARS} characters of text"
                )
            blocks.append(line)
    return "\n".join(blocks)


def _extract_txt(data: bytes) -> str:
    if len(data) > MAX_TEXT_CHARS * 4:
        raise DocumentTooLargeError(f"The document has more than {MAX_TEXT_CHARS} characters of text")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidDocumentError("The file is not valid UTF-8") from exc


def _bound(text: str) -> BoundedText:
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentTooLargeError(f"The document has more than {MAX_TEXT_CHARS} characters of text")
    stripped = text.strip()
    if not stripped:
        raise EmptyDocumentError("The document contains no extractable text")
    return BoundedText(stripped, _key=_KEY)


def _validate_extension(extension: str, text_extensions: frozenset[str]) -> None:
    if extension not in _BINARY_EXTENSIONS and extension not in text_extensions:
        raise UnsupportedFileError(f"Unsupported file extension: {extension or '<none>'}")


def _read_bounded_bytes(path: Path, *, limit: int) -> bytes:
    if path.stat().st_size > limit:
        raise DocumentTooLargeError(f"The file is larger than {limit} bytes")
    with path.open("rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise DocumentTooLargeError(f"The file is larger than {limit} bytes")
    return data


def extract(
    source: os.PathLike[str] | bytes,
    *,
    filename: str = "",
    isolated: bool = False,
    text_extensions: frozenset[str] = DEFAULT_TEXT_EXTENSIONS,
    isolated_reader: Callable[[str, bytes], str] | None = None,
) -> BoundedText:
    """Extract plain text from a ``Path`` or ``bytes`` enforcing upload and char limits."""
    if isinstance(source, os.PathLike):
        path = Path(source)
        extension = path.suffix.lower()
        _validate_extension(extension, text_extensions)
        limit = MAX_UPLOAD_BYTES if extension in _BINARY_EXTENSIONS else min(MAX_UPLOAD_BYTES, MAX_TEXT_CHARS * 4)
        data = _read_bounded_bytes(path, limit=limit)
    elif isinstance(source, (bytes, bytearray)):
        extension = os.path.splitext(filename)[1].lower()
        _validate_extension(extension, text_extensions)
        if len(source) > MAX_UPLOAD_BYTES:
            raise DocumentTooLargeError(f"The file is larger than {MAX_UPLOAD_BYTES} bytes")
        data = bytes(source)
    else:
        raise TypeError(f"extract() expects Path or bytes, got {type(source).__name__}")

    if extension in _BINARY_EXTENSIONS:
        if isolated:
            reader = isolated_reader
            if reader is None:
                from src.ingest.isolated import extract_text_isolated

                reader = extract_text_isolated
            return _bound(reader(extension, data))
        return extract_by_extension(extension, data)

    return _bound(_extract_txt(data))


def extract_text(filename: str, data: bytes) -> BoundedText:
    """Extract plain text from ``data`` according to ``filename``'s extension."""
    return extract_by_extension(os.path.splitext(filename)[1], data)


def extract_by_extension(extension: str, data: bytes) -> BoundedText:
    """Extract plain text from ``data`` read as ``extension`` (``.pdf`` or ``.docx``).

    The result is stripped and length-checked; an empty result raises
    :class:`EmptyDocumentError`. Error messages never include document contents.
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

    return _bound(text)
