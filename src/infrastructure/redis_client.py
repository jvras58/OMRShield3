"""
Conexão singleton com Redis.

Usa redis-py com decode_responses=False para suportar bytes (imagens JPEG).

Exporta:
  get_redis() -> Redis   ← para uso direto e como Depends()
"""

import logging

import redis

from src.settings.config import settings

log = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """
    Retorna a instância singleton do cliente Redis.

    Lazy-init: conecta na primeira chamada.
    Adequado para uso direto e como FastAPI Depends().

    Raises:
        redis.ConnectionError — se o Redis não estiver acessível.
    """
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=False,  # precisamos de bytes para imagens
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        # Verifica a conexão imediatamente para falhar rápido
        _client.ping()
        log.info(f"[Redis] Conectado em {settings.REDIS_URL}")
    return _client
