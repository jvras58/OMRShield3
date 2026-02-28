"""
core/alignment.py — Alinhamento de perspectiva + detecção dinâmica da zona de bolhas.

Melhoria principal: detecção de marcadores via Otsu + contornos globais,
sem regiões fixas de canto. Robusto para scanner e foto de celular.

Exporta:
  alinhar(img)                → np.ndarray  (PAGE_WIDTH × PAGE_HEIGHT, BGR)
  detectar_y_bolhas(img)      → float       (fração [0,1] do início das bolhas)
  recortar_zona_bolhas(img)   → tuple[np.ndarray, int]
"""

import logging
import os
from pathlib import Path

import cv2
import numpy as np

from src.settings.config import settings

log = logging.getLogger(__name__)

DEBUG = os.environ.get("OMR_DEBUG", "0") == "1"
DEBUG_DIR = Path("/tmp/omr_autodetect_debug")


def _dbg(name: str, img: np.ndarray) -> None:
    if not DEBUG:
        return
    DEBUG_DIR.mkdir(exist_ok=True)
    cv2.imwrite(str(DEBUG_DIR / f"{name}.jpg"), img)


def _detectar_marcadores(img: np.ndarray) -> dict[str, tuple[int, int]]:
    """
    Detecta os 4 marcadores quadrados (TL, TR, BR, BL) de forma robusta.

    1. Binarização Otsu — threshold adaptativo, funciona para scanner e celular.
    2. Contornos globais — procura quadrados sólidos em TODA a imagem.
    3. Associação por canto — cada candidato vai para o canto mais próximo,
       restrito aos 30% externos do respectivo lado.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    otsu_val, bin_img = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    log.debug(f"[Marcadores] Otsu threshold: {otsu_val:.0f}")
    _dbg("bin_otsu", bin_img)

    contours, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    area_min = (w * h) * 0.00015
    area_max = (w * h) * 0.010

    candidatos = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (area_min < area < area_max):
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        aspect = max(cw, ch) / max(min(cw, ch), 1)
        if aspect > 1.4:
            continue
        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        if hull_area == 0 or area / hull_area < 0.85:
            continue
        candidatos.append({"cx": x + cw // 2, "cy": y + ch // 2, "area": area})

    log.info(f"[Marcadores] {len(candidatos)} candidatos quadrados")

    if len(candidatos) < 4:
        raise ValueError(
            f"Marcadores insuficientes: {len(candidatos)} encontrados, esperado 4."
        )

    restricoes = {
        "TL": lambda c: c["cx"] / w < 0.30 and c["cy"] / h < 0.30,
        "TR": lambda c: c["cx"] / w > 0.70 and c["cy"] / h < 0.30,
        "BR": lambda c: c["cx"] / w > 0.70 and c["cy"] / h > 0.70,
        "BL": lambda c: c["cx"] / w < 0.30 and c["cy"] / h > 0.70,
    }
    cantos = {"TL": (0, 0), "TR": (w, 0), "BR": (w, h), "BL": (0, h)}

    resultado: dict[str, tuple[int, int]] = {}
    usados: set[int] = set()

    for nome, (ix, iy) in cantos.items():
        melhor_idx, melhor_dist = None, float("inf")
        for i, c in enumerate(candidatos):
            if i in usados or not restricoes[nome](c):
                continue
            d = ((c["cx"] - ix) ** 2 + (c["cy"] - iy) ** 2) ** 0.5
            if d < melhor_dist:
                melhor_dist = d
                melhor_idx = i
        if melhor_idx is None:
            raise ValueError(f"Marcador do canto {nome} não encontrado.")
        c = candidatos[melhor_idx]
        resultado[nome] = (c["cx"], c["cy"])
        usados.add(melhor_idx)
        log.info(
            f"[Marcadores] {nome}: ({c['cx']}, {c['cy']}) dist={melhor_dist:.0f}px"
        )

    return resultado


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def alinhar(img: np.ndarray) -> np.ndarray:
    """
    Detecta os 4 marcadores e aplica warp para PAGE_WIDTH × PAGE_HEIGHT fixos.
    Funciona para scanner e foto de celular com perspectiva.
    """
    marcadores = _detectar_marcadores(img)

    if DEBUG:
        vis = img.copy()
        cores = {
            "TL": (0, 0, 255),
            "TR": (0, 165, 255),
            "BR": (0, 255, 0),
            "BL": (255, 0, 0),
        }
        for nome, (cx, cy) in marcadores.items():
            cv2.circle(vis, (cx, cy), 25, cores[nome], 4)
            cv2.putText(
                vis,
                nome,
                (cx + 5, cy - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                cores[nome],
                2,
            )
        _dbg("marcadores_detectados", vis)

    pts = np.array([marcadores[k] for k in ("TL", "TR", "BR", "BL")], dtype="float32")
    rect = _order_points(pts)
    w, h = settings.PAGE_WIDTH, settings.PAGE_HEIGHT
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    aligned = cv2.warpPerspective(img, M, (w, h))
    log.info(f"[Warp] → {w}×{h}px")
    _dbg("aligned", aligned)
    return aligned


def detectar_y_bolhas(img: np.ndarray) -> float:
    """
    Detecta o Y de início das bolhas de forma robusta.

    Estratégia de dois passos:
      1. Encontra o primeiro grande pico de pixels escuros na janela de busca
         — esse pico corresponde à linha impressa "QUESTÃO/RESPOSTA" que
         separa o cabeçalho da grelha de bolhas.
      2. Avança a partir do pico até encontrar o VALE seguinte (região com
         < 15% do pico), que é o espaço em branco entre o cabeçalho e a
         primeira linha de bolhas. Esse ponto é o início seguro do recorte.

    A lógica de vale é superior ao simples "+2% após o pico" porque a
    largura do cabeçalho "QUESTÃO/RESPOSTA" varia entre scanner e foto.

    Parâmetros:
        img — imagem BGR já alinhada (PAGE_WIDTH × PAGE_HEIGHT)

    Retorna:
        fração [0.0, 1.0] — fallback se a detecção não for confiável.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    h = gray.shape[0]

    y_min = int(h * settings.HEADER_SEARCH_Y_MIN_FRAC)
    y_max = int(h * settings.HEADER_SEARCH_Y_MAX_FRAC)
    strip = gray[y_min:y_max, :]
    dark_per_row = (strip < 150).sum(axis=1).astype(np.float32)

    if dark_per_row.max() == 0:
        log.warning(
            f"[YBolhas] Sem pixels escuros. Fallback={settings.BOLHAS_Y_MIN_FRAC_FALLBACK}"
        )
        return settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    # Suaviza com janela maior para ignorar ruído entre bolhas individuais
    smooth = np.convolve(dark_per_row, np.ones(9) / 9, mode="same")

    # Passo 1: pico máximo = linha "QUESTÃO/RESPOSTA"
    peak_idx = int(np.argmax(smooth))
    peak_val = smooth[peak_idx]
    confidence = peak_val / max(float(np.median(smooth)), 1.0)

    if confidence < 2.0:
        log.warning(
            f"[YBolhas] Pico fraco (ratio={confidence:.1f}). "
            f"Fallback={settings.BOLHAS_Y_MIN_FRAC_FALLBACK}"
        )
        return settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    # Passo 2: após o pico, procura o vale (espaço antes da 1ª bolha)
    vale_thr = peak_val * 0.15
    vale_idx = None
    for i in range(peak_idx, len(smooth)):
        if smooth[i] < vale_thr:
            vale_idx = i
            break

    if vale_idx is not None:
        # Recua 5px para garantir margem de segurança acima da 1ª bolha
        y_result = y_min + vale_idx - 5
        log.info(
            f"[YBolhas] Pico em y={y_min + peak_idx}px, vale em y={y_min + vale_idx}px "
            f"→ início bolhas em y={y_result}px ({y_result / h:.3f})"
        )
    else:
        # Sem vale claro: fallback conservador
        log.warning("[YBolhas] Vale não encontrado após pico. Usando fallback.")
        return settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    frac = float(np.clip(y_result / h, 0.0, 1.0))

    if DEBUG:
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        cv2.line(
            vis, (0, y_min + peak_idx), (vis.shape[1], y_min + peak_idx), (0, 0, 255), 2
        )
        cv2.line(vis, (0, y_result), (vis.shape[1], y_result), (0, 255, 0), 2)
        _dbg("y_bolhas_detection", vis)

    return frac


def recortar_zona_bolhas(img: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Devolve (recorte_zona_bolhas, y_offset_px) — remove o cabeçalho da imagem.
    """
    h = img.shape[0]
    y_start = int(h * detectar_y_bolhas(img))
    y_end = int(h * settings.BOLHAS_Y_MAX_FRAC)
    recorte = img[y_start:y_end, :]
    log.info(f"[Recorte] y={y_start}:{y_end}px ({recorte.shape[0]}×{recorte.shape[1]})")
    _dbg("zona_bolhas", recorte)
    return recorte, y_start
