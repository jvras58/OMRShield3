"""
Dependências FastAPI injetáveis via Depends().

Exporta:
  get_extrator() → ExtratorCartao
  get_cache()    → GridCache
"""

from typing import Annotated

import redis
from fastapi import Depends

from src.infrastructure.cache import GridCache, make_grid_cache
from src.infrastructure.redis_client import get_redis
from src.services.cartao_service import ExtratorCartao


def get_extrator() -> ExtratorCartao:
    """
    Fornece uma instância de ExtratorCartao por request.

    ExtratorCartao não tem estado mutável entre requests,
    então a instância pode ser recriada a cada chamada sem custo
    — ou pode ser transformada em singleton aqui se necessário.
    """
    return ExtratorCartao()


def get_cache(
    redis_client: Annotated[redis.Redis, Depends(get_redis)],
) -> GridCache:
    """Fornece o GridCache conectado ao Redis por request."""
    return make_grid_cache(redis_client)


# Aliases tipados para usar nos handlers sem repetir Annotated
ExtractorDep = Annotated[ExtratorCartao, Depends(get_extrator)]
CacheDep = Annotated[GridCache, Depends(get_cache)]
