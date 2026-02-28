"""
api/app.py — Criação e configuração da aplicação FastAPI.

O lifespan gerencia o ciclo de vida do RedisBroker:
  - startup:  conecta o broker (abre pool de conexões)
  - shutdown: desconecta graciosamente

Ponto de entrada para o uvicorn:
  uv run uvicorn src.api.app:app --reload --port 8001
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.cartao.routes import router
from src.api.deps import get_broker
from src.settings.config import settings

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Conecta o broker no startup e desconecta no shutdown."""
    broker = get_broker()
    await broker.connect()
    log.info("[App] RedisBroker conectado.")
    try:
        yield
    finally:
        await broker.close()
        log.info("[App] RedisBroker desconectado.")


app = FastAPI(
    title="OMRShield API",
    description=(
        "Leitura de cartões-resposta por auto-detecção de bolhas.\n\n"
        "Funciona com foto de celular e scanner."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", summary="Health check")
async def health():
    return {"status": "ok"}
