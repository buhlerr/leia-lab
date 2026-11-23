"""Extracao de texto em um processo separado do que exibe a tela.

Um PDF patologico pode consumir memoria ou CPU sem limite enquanto e lido. Por
isso a leitura roda em outro processo: se ele travar ou morrer, a tela continua
no ar e o tempo de espera fica limitado. O conteudo do documento nunca e
registrado.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from src.ingest.extract import (
    DOCUMENT_ERRORS,
    DocumentTimeoutError,
    InvalidDocumentError,
)

_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}")


def extract_text_isolated(extension: str, data: bytes, *, timeout_s: float = 60.0) -> str:
    """Extrai o texto de ``data`` (lido como ``extension``) sem que este processo abra o arquivo.

    So a extensao vai na linha de comando do worker: o nome real do arquivo
    apareceria em ``ps``, em logs e na mensagem de ``TimeoutExpired``.

    O worker recebe os bytes por stdin e devolve um JSON com o texto ou com o
    nome e a mensagem do erro. Assim o texto do documento nao passa por logs.
    """
    if not _EXTENSION.fullmatch(extension):
        raise ValueError("extract_text_isolated recebe so a extensao (Path(nome).suffix), nunca o nome do arquivo")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "src.ingest.worker", extension],
            input=data,
            capture_output=True,
            timeout=timeout_s,
            cwd=Path(__file__).resolve().parents[2],
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise DocumentTimeoutError("The document took too long to process") from None

    if completed.returncode != 0:
        raise InvalidDocumentError("Could not read the document")

    payload = json.loads(completed.stdout)

    if "error" in payload:
        error = DOCUMENT_ERRORS.get(payload["error"], InvalidDocumentError)
        raise error(payload["message"])

    return payload["text"]
