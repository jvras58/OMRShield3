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

    # Expande o warp além dos marcadores para incluir a folga do impresso,
    # mas limitado ao espaço real disponível em cada lado para não sair do papel
    # (o scanner tem margens menores que a foto de celular).
    h_img, w_img = img.shape[:2]
    larg = float(np.linalg.norm(rect[1] - rect[0]))  # distância TL→TR
    alt = float(np.linalg.norm(rect[3] - rect[0]))  # distância TL→BL
    alvo = settings.WARP_MARGIN_FRAC  # expansão desejada (4%)

    # Espaço real além de cada marcador (com 85% de segurança)
    esp_esq = rect[0][0] * 0.85
    esp_dir = (w_img - rect[1][0]) * 0.85
    esp_top = rect[0][1] * 0.85
    esp_bot = (h_img - rect[3][1]) * 0.85

    dx_esq = min(larg * alvo, esp_esq)
    dx_dir = min(larg * alvo, esp_dir)
    dy_top = min(alt * alvo, esp_top)
    dy_bot = min(alt * alvo, esp_bot)

    rect = np.array(
        [
            [rect[0][0] - dx_esq, rect[0][1] - dy_top],  # TL
            [rect[1][0] + dx_dir, rect[1][1] - dy_top],  # TR
            [rect[2][0] + dx_dir, rect[2][1] + dy_bot],  # BR
            [rect[3][0] - dx_esq, rect[3][1] + dy_bot],  # BL
        ],
        dtype="float32",
    )

    w, h = settings.PAGE_WIDTH, settings.PAGE_HEIGHT
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    aligned = cv2.warpPerspective(img, M, (w, h))
    log.info(f"[Warp] → {w}×{h}px")
    _dbg("aligned", aligned)
    return aligned


_TEMPLATE_PATH = (
    Path(__file__).parent.parent / "assets" / "template_questao_resposta.npy"
)
_template_cache: np.ndarray | None = None


def _get_template() -> np.ndarray | None:
    global _template_cache
    if _template_cache is None and _TEMPLATE_PATH.exists():
        _template_cache = np.load(str(_TEMPLATE_PATH))
    return _template_cache


def detectar_y_bolhas(img: np.ndarray) -> float:
    """
    Localiza o início da zona de bolhas via template matching da faixa
    "QUESTÃO/RESPOSTA".

    A faixa "QUESTÃO/RESPOSTA" é o elemento visual mais estável do cartão:
    texto bold sobre fundo lilás, com posição física fixa no impresso. Após
    o warp para PAGE_HEIGHT=1400, ela aparece sempre no mesmo y relativo
    independente de ser scanner ou foto de celular.

    O template (arquivo assets/template_questao_resposta.npy) é um recorte
    em grayscale da faixa, gerado a partir de uma digitalização canônica.
    O matching usa TM_CCOEFF_NORMED — robusto a variações de brilho.

    Fallback: se o template não existir ou o score for < 0.70, usa
    análise de densidade de pixels (método anterior) como reserva.

    Parâmetros:
        img — imagem BGR já alinhada (PAGE_WIDTH × PAGE_HEIGHT)

    Retorna:
        fração [0.0, 1.0] do Y onde começa a zona de bolhas.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()

    template = _get_template()

    if template is not None:
        # Região de busca: 50%–85% da altura (onde a faixa sempre está)
        y_search_min = int(h * 0.50)
        y_search_max = int(h * 0.85)

        # Mesma faixa horizontal usada ao criar o template (1/4 a 3/4)
        x0, x1 = w // 4, 3 * w // 4
        region = gray[y_search_min:y_search_max, x0:x1]

        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, max_loc = cv2.minMaxLoc(result)
        y_match = y_search_min + max_loc[1]

        log.info(
            f"[YBolhas] Template match: y={y_match}px frac={y_match / h:.4f} score={score:.4f}"
        )

        if score >= 0.70:
            frac = float(np.clip(y_match / h, 0.0, 1.0))

            if DEBUG:
                vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                th = template.shape[0]
                cv2.rectangle(vis, (x0, y_match), (x1, y_match + th), (0, 255, 0), 3)
                _dbg("y_bolhas_detection", vis)

            return frac

        log.warning(
            f"[YBolhas] Score baixo ({score:.3f}), usando fallback por densidade."
        )
    else:
        log.warning(
            f"[YBolhas] Template não encontrado em {_TEMPLATE_PATH}. Usando fallback."
        )

    # ── Fallback: análise de densidade (usado se template indisponível) ──
    gray_norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    y_min = int(h * settings.HEADER_SEARCH_Y_MIN_FRAC)
    y_max = int(h * settings.HEADER_SEARCH_Y_MAX_FRAC)
    dark = (gray_norm[y_min:y_max, :] < 150).sum(axis=1).astype(np.float32)

    if dark.max() == 0:
        log.warning(
            f"[YBolhas] Fallback: sem pixels escuros → {settings.BOLHAS_Y_MIN_FRAC_FALLBACK}"
        )
        return settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    smooth = np.convolve(dark, np.ones(9) / 9, mode="same")
    peak_idx = int(np.argmax(smooth))
    peak_val = smooth[peak_idx]
    confidence = peak_val / max(float(np.median(smooth)), 1.0)

    if confidence < 2.0:
        log.warning(
            f"[YBolhas] Fallback: pico fraco → {settings.BOLHAS_Y_MIN_FRAC_FALLBACK}"
        )
        return settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    inicio_idx = peak_idx
    for i in range(peak_idx, 0, -1):
        if smooth[i] < peak_val * 0.15:
            inicio_idx = i
            break

    frac = float(np.clip((y_min + inicio_idx) / h, 0.0, 1.0))
    log.info(f"[YBolhas] Fallback densidade: frac={frac:.4f}")
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
