"""API HTTP para a camada FE separada: contrato de avaliacao de contratos.

Entry point: ``python -m src.api`` (uvicorn em ``0.0.0.0:${PORT:-8080}``,
token de servico ``LEIA_API_TOKEN`` exigido). O OpenAPI em ``/docs`` e o
contrato para o front-end. Privacidade: todo upload e mascarado em
``prepare_input`` ANTES de qualquer chamada externa, e o nome real do arquivo
nunca sai do processo (so o apelido ``documento-<sha8>.<ext>``).
"""
