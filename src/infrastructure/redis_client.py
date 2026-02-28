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
_pool: redis.ConnectionPool | None = None


def get_redis() -> redis.Redis:
    """
    Retorna a instância singleton do cliente Redis com connection pool.

    O pool permite que múltiplas threads/requests do mesmo worker
    reutilizem conexões em vez de abrir uma nova a cada chamada.

    Raises:
        redis.ConnectionError — se o Redis não estiver acessível.
    """
    global _client, _pool
    if _client is None:
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=False,  # precisamos de bytes para imagens
            socket_connect_timeout=5,
            socket_timeout=5,
            max_connections=20,  # máximo de conexões simultâneas por worker
            health_check_interval=30,
        )
        _client = redis.Redis(connection_pool=_pool)
        # Verifica a conexão imediatamente para falhar rápido
        _client.ping()
        log.info(f"[Redis] Conectado em {settings.REDIS_URL} (pool max_connections=20)")
    return _client
