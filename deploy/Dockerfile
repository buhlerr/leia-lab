# Admin da Leia (Django + gunicorn). Build da raiz do repo:
#   docker build -f deploy/Dockerfile -t leia-admin .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

# Dependencias pelo lockfile do repo (as mesmas versoes da suite), sem as de desenvolvimento.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY deploy/entrypoint.sh .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh \
    && useradd --system --home /app leia && chown -R leia /app
USER leia

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
