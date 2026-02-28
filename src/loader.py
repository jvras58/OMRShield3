"""
loader.py — Carregamento e alinhamento de imagens.

Detecta os 4 marcadores quadrados nos cantos e aplica warp de perspectiva.
Idêntico ao projeto principal — não depende de template.
"""

import logging
import os
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

PAGE_WIDTH = 1000

_MX   = 0.10
_MY_T = 0.08
_MY_B = 0.07

DEBUG     = os.environ.get("OMR_DEBUG", "0") == "1"
DEBUG_DIR = Path("/tmp/omr_autodetect_debug")


def _dbg(name: str, img: np.ndarray):
    if not DEBUG:
        return
    DEBUG_DIR.mkdir(exist_ok=True)
    cv2.imwrite(str(DEBUG_DIR / f"{name}.jpg"), img)


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s    = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _calcular_page_height(rect: np.ndarray) -> int:
    tl, tr, bl, br = rect[0], rect[1], rect[3], rect[2]
    card_w = float(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    card_h = float(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if card_w < 1:
        raise ValueError("Warp: largura calculada < 1px — marcadores inválidos.")
    return int(PAGE_WIDTH * card_h / card_w)


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect   = _order_points(pts)
    page_h = _calcular_page_height(rect)
    dst    = np.array(
        [[0, 0], [PAGE_WIDTH - 1, 0],
         [PAGE_WIDTH - 1, page_h - 1], [0, page_h - 1]],
        dtype="float32",
    )
    M      = cv2.getPerspectiveTransform(rect, dst)
    result = cv2.warpPerspective(image, M, (PAGE_WIDTH, page_h))
    log.info(f"[Warp] → {PAGE_WIDTH}×{page_h}px")
    return result


def _encontrar_quadradinho(quad: np.ndarray, nome: str = "") -> tuple[int, int, int, int]:
    qh, qw    = quad.shape[:2]
    area_quad = qh * qw

    blur = cv2.GaussianBlur(quad, (3, 3), 0)
    _, bin_ = cv2.threshold(blur, 80, 255, cv2.THRESH_BINARY_INV)
    _dbg(f"quad_bin_{nome}", bin_)

    contours, _ = cv2.findContours(bin_, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidatos = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (area_quad * 0.0005 < area < area_quad * 0.20):
            continue
        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        if hull_area > 0 and (area / hull_area) < 0.85:
            continue
        peri  = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.05 * peri, True)
        if not (4 <= len(approx) <= 6):
            continue
        bx, by, bw, bh = cv2.boundingRect(approx)
        if bw < 8 or bh < 8:
            continue
        if max(bw, bh) / max(min(bw, bh), 1) > 2.0:
            continue
        roi  = quad[by : by + bh, bx : bx + bw]
        if roi.size == 0 or float(cv2.mean(roi)[0]) > 100:
            continue
        candidatos.append({
            "cx": bx + bw // 2, "cy": by + bh // 2,
            "bx": bx, "by": by, "bw": bw, "bh": bh,
            "area": area,
        })

    if not candidatos:
        raise ValueError(f"[Alinhamento] {nome}: nenhum marcador encontrado.")

    melhor = max(candidatos, key=lambda c: c["area"])
    cx, cy = melhor["cx"], melhor["cy"]
    bx, by, bw, bh = melhor["bx"], melhor["by"], melhor["bw"], melhor["bh"]
    corner_x = bx if cx < qw // 2 else bx + bw
    corner_y = by if cy < qh // 2 else by + bh

    log.info(
        f"[Alinhamento] {nome}: area={int(melhor['area'])} "
        f"corner=({corner_x},{corner_y})"
    )
    return cx, cy, corner_x, corner_y


def _alinhar(img: np.ndarray) -> np.ndarray:
    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    h, w  = gray.shape
    mx    = int(w * _MX)
    my_t  = int(h * _MY_T)
    my_b  = int(h * _MY_B)

    regioes = {
        "TL": (gray[0:my_t,       0:mx],          0,      0),
        "TR": (gray[0:my_t,       w - mx : w],    w - mx, 0),
        "BL": (gray[h - my_b : h, 0:mx],          0,      h - my_b),
        "BR": (gray[h - my_b : h, w - mx : w],   w - mx, h - my_b),
    }

    corners = []
    for nome, (regiao, ox, oy) in regioes.items():
        _dbg(f"regiao_{nome}", regiao)
        _, _, cx, cy = _encontrar_quadradinho(regiao, nome)
        corners.append([cx + ox, cy + oy])

    aligned = _four_point_transform(img, np.array(corners, dtype="float32"))
    _dbg("aligned", aligned)
    return aligned


def carregar_imagem(img_path: str) -> np.ndarray:
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError(f"Não foi possível abrir '{img_path}'.")
    return _alinhar(img)


def carregar_imagem_bytes(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Não foi possível decodificar a imagem.")
    return _alinhar(img)
