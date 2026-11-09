"""Text extraction for draft documents uploaded as PDF or DOCX.

The format is chosen from ``filename``'s extension, case-insensitively. Read
failures are normalized into :class:`DocumentError` subclasses so callers can
distinguish unsupported formats, unreadable files and documents with no text
(for example scanned PDFs) without inspecting library-specific exceptions.
"""

from __future__ import annotations

import io
import os

import docx
import pypdf
from docx.text.paragraph import Paragraph


class DocumentError(ValueError):
    """Base class for failures while reading a draft document."""


class UnsupportedFileError(DocumentError):
    """Raised when ``filename`` has an extension this module cannot read."""


class InvalidDocumentError(DocumentError):
    """Raised when the file is corrupted or cannot be read by its library."""


class EmptyDocumentError(DocumentError):
    """Raised when the document yields no text (for example a scanned PDF)."""


def _extract_pdf(data: bytes) -> str:
    """Return the text of every PDF page, joining pages with a blank line."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


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
    """Extract plain text from ``data`` according to ``filename``'s extension.

    Supports ``.pdf`` and ``.docx``. The result is stripped; an empty result
    raises :class:`EmptyDocumentError`. Error messages never include document
    contents.
    """
    extension = os.path.splitext(filename)[1].lower()

    if extension == ".pdf":
        extractor = _extract_pdf
    elif extension == ".docx":
        extractor = _extract_docx
    else:
        raise UnsupportedFileError(f"Unsupported file extension: {extension or '<none>'}")

    try:
        text = extractor(data)
    except Exception as exc:
        raise InvalidDocumentError("Could not read the document") from exc

    text = text.strip()
    if not text:
        raise EmptyDocumentError("The document contains no extractable text")
    return text
