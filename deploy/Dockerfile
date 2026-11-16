# Admin da Leia (Django + gunicorn). Build da raiz do repo:
#   docker build -f deploy/Dockerfile -t leia-admin .
#
# Tamanho (bead leia-lab-8tr.14): a imagem chegou a 3,3 GB e encheu o disco do CT 116 (14 GB,
# o mesmo do Postgres). Duas regras para nao voltar:
#   * nada de "chown -R" depois do uv sync: copiaria a .venv inteira numa camada nova;
#     o usuario e criado antes e so o que o entrypoint escreve (src/, para o collectstatic) e dele;
#   * UV_NO_CACHE: o cache do uv nao fica gravado na camada.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv

RUN useradd --system --home /app leia && mkdir /app && chown leia /app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH=/app/.venv/bin:$PATH

# Dependencias pelo lockfile do repo (as mesmas versoes da suite), sem as de desenvolvimento.
# Ficam do root: o processo so le a .venv.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=leia src/ src/
COPY --chmod=755 deploy/entrypoint.sh .
RUN sed -i 's/\r$//' entrypoint.sh
USER leia

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
