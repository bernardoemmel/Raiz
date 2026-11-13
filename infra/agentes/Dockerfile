# syntax=docker/dockerfile:1
# Imagem única da API/MCP, migrações, worker e agenda; dependências travadas no uv.lock.
FROM ghcr.io/astral-sh/uv:0.9.5 AS uv
FROM rust:1.91.1-slim-bookworm AS rust
FROM python:3.12.12-slim-bookworm AS construir
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV PATH="/usr/local/cargo/bin:$PATH" RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY nativo ./nativo
# O certificado opcional só existe durante o build; nunca entra nas camadas finais.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca CARGO_HTTP_CAINFO=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --all-extras --no-dev --no-editable --no-install-project
COPY . .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca CARGO_HTTP_CAINFO=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --all-extras --no-dev --no-editable && rm -rf nativo/raiz_iov/target
RUN python scripts/proveniencia_imagem.py --saida /app/proveniencia.json

FROM python:3.12.12-slim-bookworm AS executar
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo PYTHONPATH=/app RAIZ_MOTOR_DIR_TRABALHO=/app/dados/motor
WORKDIR /app
RUN groupadd --gid 10001 raiz && useradd --uid 10001 --gid 10001 --no-create-home raiz
COPY --from=construir --chown=10001:10001 /app /app
RUN chmod -R a+rX /app && mkdir -p /app/dados && chown 10001:10001 /app/dados
USER 10001:10001
EXPOSE 8000
CMD ["raiz", "api", "--host", "0.0.0.0", "--porta", "8000"]
