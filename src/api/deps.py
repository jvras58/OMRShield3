"""
services/deps.py — Dependências FastAPI injetáveis via Depends().

Centralizar aqui facilita o override em testes:
  app.dependency_overrides[get_extrator] = lambda: MockExtrator()
  app.dependency_overrides[get_cache]    = lambda: FakeCache()
  app.dependency_overrides[get_broker]   = lambda: FakeBroker()

Exporta:
  get_extrator() → ExtratorCartao
  get_cache()    → GridCache
  get_broker()   → RedisBroker
"""

from typing import Annotated

import redis
from fastapi import Depends
from faststream.redis import RedisBroker

from src.infrastructure.cache import GridCache, make_grid_cache
from src.infrastructure.redis_client import get_redis
from src.services.cartao_service import ExtratorCartao
from src.settings.config import settings

_broker: RedisBroker | None = None


def get_broker() -> RedisBroker:
    """
    Retorna o RedisBroker singleton.

    O broker é compartilhado entre requests da API para publicação de mensagens.
    A conexão é estabelecida no startup do app (ver app.py lifespan).
    """
    global _broker
    if _broker is None:
        _broker = RedisBroker(settings.REDIS_URL)
    return _broker


def get_extrator() -> ExtratorCartao:
    """
    Fornece uma instância de ExtratorCartao por request.

    ExtratorCartao não tem estado mutável entre requests,
    então a instância pode ser recriada a cada chamada sem custo.
    """
    return ExtratorCartao()


def get_cache(
    redis_client: Annotated[redis.Redis, Depends(get_redis)],
) -> GridCache:
    """Fornece o GridCache conectado ao Redis por request."""
    return make_grid_cache(redis_client)


ExtractorDep = Annotated[ExtratorCartao, Depends(get_extrator)]
CacheDep = Annotated[GridCache, Depends(get_cache)]
BrokerDep = Annotated[RedisBroker, Depends(get_broker)]
