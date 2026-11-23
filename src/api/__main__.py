"""Entrada da API: ``python -m src.api`` (uvicorn em ``0.0.0.0:${PORT:-8080}``)."""

from __future__ import annotations

import os

import uvicorn

from src.api.app import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
