"""
infrastructure/cache.py — Cache de grids processados via Redis.

Serialização:
  img       → JPEG bytes       (redis key: "grid:{job_id}:img")
  respostas → JSON string      (redis key: "grid:{job_id}:meta")
  dia       → embutido no meta

Chave temporária para o batch assíncrono:
  imagem raw → bytes           (redis key: "temp:{job_id}")

Ambas as keys recebem o mesmo TTL (CACHE_TTL_SECONDS).

Exporta:
  GridCache        — classe do cache
  make_grid_cache  — factory para Depends()
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
_KEY_TEMP = "temp:{job_id}"


class GridCache:
    """
    Cache de grids com backend Redis.
    Thread-safe e multi-worker: qualquer worker acessa qualquer job_id.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._r = redis_client
        self._ttl = settings.CACHE_TTL_SECONDS

    def set(
        self,
        job_id: str,
        img: np.ndarray,
        respostas: dict,
        dia: int,
        cpf: str | None = None,
        avisos: list[str] | None = None,
    ) -> None:
        """Serializa e armazena imagem + metadados no Redis com TTL."""
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError(f"[Cache] Falha ao encodar imagem para job_id={job_id}")

        meta = json.dumps(
            {
                "respostas": {str(k): v for k, v in respostas.items()},
                "dia": dia,
                "status": "done",
                "cpf": cpf,
                "avisos": avisos or [],
            }
        )

        pipe = self._r.pipeline()
        pipe.setex(_KEY_IMG.format(job_id=job_id), self._ttl, buf.tobytes())
        pipe.setex(_KEY_META.format(job_id=job_id), self._ttl, meta.encode())
        pipe.execute()

        log.debug(f"[Cache] SET job_id={job_id} img={len(buf.tobytes()) // 1024}KB")

    def get(self, job_id: str) -> tuple[np.ndarray, dict, int] | None:
        """Recupera (img, respostas, dia) ou None se expirado/inexistente."""
        pipe = self._r.pipeline()
        pipe.get(_KEY_IMG.format(job_id=job_id))
        pipe.get(_KEY_META.format(job_id=job_id))
        img_bytes, meta_bytes = pipe.execute()

        if img_bytes is None or meta_bytes is None:
            return None

        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            log.error(f"[Cache] Falha ao decodificar imagem job_id={job_id}")
            return None

        meta = json.loads(meta_bytes.decode())
        respostas = {int(k): v for k, v in meta["respostas"].items()}
        dia = int(meta["dia"])

        return img, respostas, dia

    def __contains__(self, job_id: str) -> bool:
        return bool(self._r.exists(_KEY_IMG.format(job_id=job_id)))

    def get_status(self, job_id: str) -> dict | None:
        """
        Retorna metadados do job sem carregar a imagem.
        Retorna None se o job ainda não foi processado ou expirou.
        """
        meta_bytes = self._r.get(_KEY_META.format(job_id=job_id))
        if meta_bytes is None:
            return None
        meta = json.loads(meta_bytes.decode())
        return {
            "status": meta.get("status", "done"),
            "respostas": {int(k): v for k, v in meta.get("respostas", {}).items()},
            "dia": meta.get("dia"),
            "cpf": meta.get("cpf"),
            "avisos": meta.get("avisos", []),
        }

    def set_failed(self, job_id: str, avisos: list[str]) -> None:
        """Marca um job como falho (worker encontrou erro irrecuperável)."""
        meta = json.dumps({"status": "failed", "avisos": avisos, "respostas": {}})
        self._r.setex(_KEY_META.format(job_id=job_id), self._ttl, meta.encode())
        log.warning(f"[Cache] job_id={job_id} marcado como failed")

    def set_temp(self, job_id: str, img_bytes: bytes) -> None:
        """Armazena imagem raw para consumo pelo worker. TTL curto: 10 min."""
        self._r.setex(_KEY_TEMP.format(job_id=job_id), 600, img_bytes)

    def get_temp(self, job_id: str) -> bytes | None:
        """Recupera imagem raw. None se expirada/inexistente."""
        return self._r.get(_KEY_TEMP.format(job_id=job_id))

    def del_temp(self, job_id: str) -> None:
        """Remove imagem raw após processamento bem-sucedido."""
        self._r.delete(_KEY_TEMP.format(job_id=job_id))


def make_grid_cache(redis_client: redis.Redis) -> GridCache:
    """Factory usada pelo Depends() da API."""
    return GridCache(redis_client)
