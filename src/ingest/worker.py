"""Extracao de texto em um processo separado, lida por stdin e stdout.

Executado como ``python -m src.ingest.worker <filename>``: le os bytes do
arquivo de stdin e escreve um JSON UTF-8 em stdout. O processo que abriu a tela
nao le o arquivo enviado, portanto um PDF patologico nao trava nem derruba a
tela. O conteudo do documento nunca e registrado.
"""

from __future__ import annotations

import json
import sys

from src.ingest.extract import DocumentError, extract_text


def main() -> int:
    """Le o arquivo de stdin e escreve o texto ou o erro em stdout."""
    filename = sys.argv[1]
    data = sys.stdin.buffer.read()
    try:
        payload = {"text": extract_text(filename, data)}
    except DocumentError as exc:
        payload = {"error": type(exc).__name__, "message": str(exc)}
    sys.stdout.buffer.write(json.dumps(payload).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
