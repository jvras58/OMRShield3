# ─────────────────────────────────────────────────────────────────────────────
# Builder stage
FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# 1. Instalar o build backend (hatchling)
COPY pyproject.toml uv.lock* ./
RUN uv pip install --system --no-cache hatchling

# 2. Copiar o código-fonte ANTES de instalar o pacote
#    (hatchling precisa do src/ para construir o wheel)
COPY src/ ./src/

# 3. Instalar o pacote + todas as dependências
RUN uv pip install --system --no-cache --no-build-isolation .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-por libgl1 libglib2.0-0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app
COPY src/ ./src/

RUN chown -R appuser:appuser /app
USER appuser

VOLUME ["/data"]

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]