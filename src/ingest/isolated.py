"""Extracao de texto em um processo separado do que exibe a tela.

Um PDF patologico pode consumir memoria ou CPU sem limite enquanto e lido. Por
isso a leitura roda em outro processo: se ele travar ou morrer, a tela continua
no ar e o tempo de espera fica limitado. O conteudo do documento nunca e
registrado.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.ingest.extract import (
    DocumentTooLargeError,
    EmptyDocumentError,
    InvalidDocumentError,
    UnsupportedFileError,
)

_ERRORS = {
    error.__name__: error
    for error in (
        UnsupportedFileError,
        InvalidDocumentError,
        EmptyDocumentError,
        DocumentTooLargeError,
    )
}


def extract_text_isolated(filename: str, data: bytes, *, timeout_s: float = 60.0) -> str:
    """Extrai o texto de ``data`` sem que este processo abra o arquivo.

    O worker recebe os bytes por stdin e devolve um JSON com o texto ou com o
    nome e a mensagem do erro. Assim o texto do documento nao passa por logs.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "src.ingest.worker", filename],
            input=data,
            capture_output=True,
            timeout=timeout_s,
            cwd=Path(__file__).resolve().parents[2],
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocumentTooLargeError("The document took too long to process") from exc

    if completed.returncode != 0:
        raise InvalidDocumentError("Could not read the document")

    payload = json.loads(completed.stdout)

    if "error" in payload:
        error = _ERRORS.get(payload["error"], InvalidDocumentError)
        raise error(payload["message"])

    return payload["text"]
