"""
api/app.py — Criação e configuração da aplicação FastAPI.

Ponto de entrada para o uvicorn:
  uv run uvicorn src.api.app:app --reload --port 8001
"""

import logging

from fastapi import FastAPI

from src.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="OMR AutoDetect",
    description=(
        "Leitura de cartões-resposta SIMUREKA por auto-detecção de bolhas.\n\n"
        "Funciona com foto de celular e scanner — sem necessidade de template."
    ),
    version="1.0.0",
)

app.include_router(router)
