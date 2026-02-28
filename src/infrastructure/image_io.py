"""
infrastructure/image_io.py — I/O de imagens: leitura de arquivo ou bytes.

Exporta:
  carregar_imagem(img_path: str) -> np.ndarray
  carregar_imagem_bytes(data: bytes) -> np.ndarray
"""

import logging

import cv2
import numpy as np

from src.core.alignment import alinhar

log = logging.getLogger(__name__)


def carregar_imagem(img_path: str) -> np.ndarray:
    """Lê imagem do disco, alinha perspectiva e retorna array BGR."""
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError(f"Não foi possível abrir '{img_path}'.")
    return alinhar(img)


def carregar_imagem_bytes(data: bytes) -> np.ndarray:
    """Decodifica bytes JPEG/PNG, alinha perspectiva e retorna array BGR."""
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Não foi possível decodificar a imagem.")
    return alinhar(img)
