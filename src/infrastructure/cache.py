"""
infrastructure/cache.py — Cache em memória para grids processados.

Limite configurável via CACHE_MAX; remove o item mais antigo ao ultrapassar.

Exporta:
  GridCache — classe do cache
  grid_cache — instância global pronta para importar
"""

import numpy as np

_DEFAULT_MAX = 100


class GridCache:
    """
    Armazena tuplas (img_alinhada, respostas, dia) indexadas por job_id.
    Thread-safe apenas para leituras concorrentes simples (processo único).
    """

    def __init__(self, max_size: int = _DEFAULT_MAX) -> None:
        self._max = max_size
        self._data: dict[str, tuple[np.ndarray, dict, int]] = {}

    def set(self, job_id: str, img: np.ndarray, respostas: dict, dia: int) -> None:
        """Insere ou atualiza uma entrada; remove a mais antiga se necessário."""
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)))
        self._data[job_id] = (img, respostas, dia)

    def get(self, job_id: str) -> tuple[np.ndarray, dict, int] | None:
        """Retorna (img, respostas, dia) ou None se não encontrado."""
        return self._data.get(job_id)

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._data


grid_cache = GridCache()
