"""
Cache de grids processados via Redis.

Serialização:
  img      → JPEG bytes        (redis key: "grid:{job_id}:img")
  respostas → JSON string      (redis key: "grid:{job_id}:meta")
  dia       → embutido no meta

Ambas as keys recebem o mesmo TTL (CACHE_TTL_SECONDS).
Isso garante que job_ids de workers diferentes sejam visíveis a todos,
e que entradas antigas expirem automaticamente sem acumular memória.

Exporta:
  GridCache   — classe do cache
  grid_cache  — instância global pronta para importar
"""

import json
import logging

import cv2
import numpy as np
import redis

from src.settings.config import settings

log = logging.getLogger(__name__)

_KEY_IMG = "grid:{job_id}:img"
_KEY_META = "grid:{job_id}:meta"


class GridCache:
    """
    Cache de grids processados com backend Redis.

    Thread-safe e multi-worker: qualquer processo que conhece o job_id
    consegue recuperar a imagem, independente de qual worker a gerou.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._r = redis_client
        self._ttl = settings.CACHE_TTL_SECONDS

    def set(self, job_id: str, img: np.ndarray, respostas: dict, dia: int) -> None:
        """Serializa e armazena imagem + metadados no Redis com TTL."""

        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError(f"[Cache] Falha ao encodar imagem para job_id={job_id}")

        meta = json.dumps(
            {"respostas": {str(k): v for k, v in respostas.items()}, "dia": dia}
        )

        pipe = self._r.pipeline()
        pipe.setex(_KEY_IMG.format(job_id=job_id), self._ttl, buf.tobytes())
        pipe.setex(_KEY_META.format(job_id=job_id), self._ttl, meta.encode())
        pipe.execute()

        log.debug(
            f"[Cache] SET job_id={job_id} ttl={self._ttl}s img={len(buf.tobytes()) // 1024}KB"
        )

    def get(self, job_id: str) -> tuple[np.ndarray, dict, int] | None:
        """
        Recupera (img, respostas, dia) ou None se expirado/inexistente.

        Verifica ambas as keys em pipeline para minimizar round-trips.
        """
        pipe = self._r.pipeline()
        pipe.get(_KEY_IMG.format(job_id=job_id))
        pipe.get(_KEY_META.format(job_id=job_id))
        img_bytes, meta_bytes = pipe.execute()

        if img_bytes is None or meta_bytes is None:
            log.debug(f"[Cache] MISS job_id={job_id}")
            return None

        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            log.error(f"[Cache] Falha ao decodificar imagem para job_id={job_id}")
            return None

        meta = json.loads(meta_bytes.decode())
        respostas = {int(k): v for k, v in meta["respostas"].items()}
        dia = int(meta["dia"])

        log.debug(f"[Cache] HIT job_id={job_id}")
        return img, respostas, dia

    def __contains__(self, job_id: str) -> bool:
        return bool(self._r.exists(_KEY_IMG.format(job_id=job_id)))


def make_grid_cache(redis_client: redis.Redis) -> GridCache:
    """Factory usada pelo Depends() da API."""
    return GridCache(redis_client)
