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

from src.api.cartao.routes import router
from src.api.deps import get_broker

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
    title="OMR AutoDetect",
    description=(
        "Leitura de cartões-resposta SIMUREKA por auto-detecção de bolhas.\n\n"
        "Funciona com foto de celular e scanner."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
