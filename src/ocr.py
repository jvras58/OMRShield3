"""
ocr.py — Extração de CPF via Tesseract.
Idêntico ao projeto principal.
"""

import re
import logging
from typing import Optional

import cv2
import numpy as np
import pytesseract

from src.config import CPF_ROI, MAX_OCR_RETRIES

log = logging.getLogger(__name__)

_CONFIGS_TESS = [
    "--oem 3 --psm 6  -c tessedit_char_whitelist=0123456789.-",
    "--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789.-",
    "--oem 1 --psm 6",
]
_PADROES_CPF = [
    r"\d{3}[\.\-]?\d{3}[\.\-]?\d{3}[\-]?\d{2}",
    r"\d{11}",
]


def _formato_ok(d: str) -> bool:
    return len(d) == 11 and len(set(d)) > 1


def validar_cpf(cpf: str) -> bool:
    d = re.sub(r"\D", "", cpf)
    if not _formato_ok(d):
        return False

    def dig(parte, pesos):
        r = sum(int(c) * p for c, p in zip(parte, pesos)) % 11
        return 0 if r < 2 else 11 - r

    return int(d[9]) == dig(d[:9], range(10, 1, -1)) and int(d[10]) == dig(
        d[:10], range(11, 1, -1)
    )


def formatar_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def ocr_para_cpf(img: np.ndarray) -> Optional[str]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    for cfg in _CONFIGS_TESS:
        texto = pytesseract.image_to_string(gray, config=cfg, lang="por")
        for padrao in _PADROES_CPF:
            for m in re.findall(padrao, texto):
                d = re.sub(r"\D", "", m)
                if validar_cpf(d):
                    return formatar_cpf(d)
    return None


def extrair_cpf(img: np.ndarray) -> tuple[Optional[str], int]:
    """Orquestra 3 estratégias: imagem completa, ROI, ROI zoom+denoised."""
    x0_f, x1_f, y0_f, y1_f = CPF_ROI
    h, w = img.shape[:2]
    roi  = img[int(h * y0_f) : int(h * y1_f), int(w * x0_f) : int(w * x1_f)]

    estrategias = [("completa", img), ("roi_cpf", roi)]
    if roi.size > 0:
        up = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        dn = cv2.fastNlMeansDenoisingColored(up, None, 10, 10, 7, 21)
        estrategias.append(("roi_zoom", dn))

    for i, (nome, frame) in enumerate(estrategias[:MAX_OCR_RETRIES], 1):
        cpf = ocr_para_cpf(frame)
        if cpf:
            log.info(f"[CPF] Encontrado em tentativa {i} ({nome}): {cpf}")
            return cpf, i
        log.warning(f"[CPF] '{nome}' não detectou CPF.")

    log.error("[CPF] Todas as tentativas falharam.")
    return None, MAX_OCR_RETRIES
