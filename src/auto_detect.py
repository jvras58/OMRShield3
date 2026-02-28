"""
auto_detect.py — Detecção automática de bolhas sem template.

Responsabilidade única: dado um cartão alinhado (saída do loader),
retorna {numero_questao: letra_resposta} sem precisar de omr_template.json.

Pipeline:
  1. encontrar_separadores()  → gaps brancos que dividem os N_BLOCOS
  2. hough_bolhas()           → HoughCircles por bloco → (cx, cy, r)
  3. calibrar_colunas()       → KMeans em X → posições das N_ALTERNATIVAS colunas
  4. calibrar_linhas()        → KMeans em Y → oy + labelsGap
  5. ler_bloco()              → mede fill em grid completo → {qi: [v0..v4]}
  6. detectar_todos()         → orquestra blocos e aplica threshold
"""

import logging
from typing import Optional

import cv2
import numpy as np

from src.config import (
    N_BLOCOS, N_QUESTOES_POR_BLOCO, N_ALTERNATIVAS, ALTERNATIVAS,
    BOLHAS_Y_MIN_FRAC, BOLHAS_Y_MAX_FRAC,
    HOUGH_MIN_DIST, HOUGH_PARAM1, HOUGH_PARAM2,
    HOUGH_MIN_RADIUS, HOUGH_MAX_RADIUS,
    HOUGH_BLUR_KERNEL, HOUGH_BLUR_SIGMA,
    SEP_MIN_GAP_PX, SEP_DARK_THR, SEP_PIXEL_THR,
    FILL_RADIUS, FILL_MARGIN_FRAC,
    MIN_JUMP_GLOBAL, MIN_JUMP_LOCAL, MAX_UNMARKED_VAL,
)

log = logging.getLogger(__name__)

# sklearn é opcional — se não tiver, usa clustering simples por mediana
try:
    from sklearn.cluster import KMeans as _KMeans
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False
    log.warning("[AutoDetect] sklearn não instalado — usando clustering simples.")


# ─── Clustering ────────────────────────────────────────────────────────────────

def _kmeans_1d(values: list[float], k: int) -> list[float]:
    """Retorna k centros ordenados. Usa sklearn se disponível, senão divisão uniforme."""
    if len(values) < k:
        return sorted(values)

    if _HAS_SKLEARN:
        arr = np.array(values).reshape(-1, 1)
        km  = _KMeans(n_clusters=k, n_init=10, random_state=0).fit(arr)
        return sorted(float(c) for c in km.cluster_centers_.flatten())

    # Fallback: dividir o range em k buckets e usar a mediana de cada
    sorted_v = sorted(values)
    bucket   = max(1, len(sorted_v) // k)
    centers  = []
    for i in range(k):
        chunk = sorted_v[i * bucket : (i + 1) * bucket]
        if chunk:
            centers.append(float(np.median(chunk)))
    # Preencher se ficaram buckets vazios
    while len(centers) < k:
        centers.append(centers[-1] + 20 if centers else 50.0)
    return sorted(centers[:k])


# ─── 1. Separadores ────────────────────────────────────────────────────────────

def encontrar_separadores(gray: np.ndarray, y_min: int, y_max: int) -> list[int]:
    """
    Detecta as posições X dos gaps brancos verticais que separam os blocos.

    Retorna lista de N_BLOCOS+1 valores: [x_inicio_b1, x_fim_b1/inicio_b2, ..., x_fim_bN]
    O primeiro elemento é 0 e o último é gray.shape[1].
    """
    h, w = gray.shape
    strip = gray[y_min:y_max, :]

    # Perfil: número de pixels escuros por coluna
    dark_per_col = (strip < SEP_PIXEL_THR).sum(axis=0)

    # Encontrar regiões de gap (pouco escuro)
    in_gap   = False
    gap_start = 0
    gaps: list[tuple[int, int]] = []          # (x_start, x_end) dos gaps

    for x, dark in enumerate(dark_per_col):
        if dark < SEP_DARK_THR and not in_gap:
            in_gap    = True
            gap_start = x
        elif dark >= SEP_DARK_THR and in_gap:
            in_gap = False
            if x - gap_start >= SEP_MIN_GAP_PX:
                gaps.append((gap_start, x))

    if in_gap and w - gap_start >= SEP_MIN_GAP_PX:
        gaps.append((gap_start, w))

    log.debug(f"[Sep] gaps brutos: {gaps}")

    # Converter gaps → fronteiras entre blocos (centro de cada gap)
    midpoints = [(s + e) // 2 for s, e in gaps]

    # Se detectou exatamente N_BLOCOS-1 separadores → perfeito
    if len(midpoints) == N_BLOCOS - 1:
        seps = [0] + midpoints + [w]
        log.info(f"[Sep] {N_BLOCOS} blocos detectados: {seps}")
        return seps

    # Se detectou mais: pegar os N_BLOCOS-1 mais espaçados / mais largos
    if len(midpoints) > N_BLOCOS - 1:
        # Ordenar por largura do gap (maior = separador real)
        gaps_sorted = sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)
        best        = sorted(gaps_sorted[: N_BLOCOS - 1], key=lambda g: g[0])
        midpoints   = [(s + e) // 2 for s, e in best]
        seps        = [0] + midpoints + [w]
        log.info(f"[Sep] filtrados para {N_BLOCOS} blocos: {seps}")
        return seps

    # Se detectou menos: estimar posições uniformemente
    log.warning(
        f"[Sep] Esperado {N_BLOCOS - 1} separadores, detectado {len(midpoints)}. "
        "Usando divisão uniforme."
    )
    block_w = w // N_BLOCOS
    seps    = [i * block_w for i in range(N_BLOCOS + 1)]
    seps[-1] = w
    return seps


# ─── 2. Hough por bloco ────────────────────────────────────────────────────────

def hough_bolhas(gray: np.ndarray, x_min: int, x_max: int,
                 y_min: int, y_max: int) -> list[tuple[int, int, int]]:
    """
    Detecta círculos (bolhas) numa região retangular da imagem.
    Retorna lista de (cx, cy, r) em coordenadas absolutas da imagem.
    """
    strip   = gray[y_min:y_max, x_min:x_max]
    blurred = cv2.GaussianBlur(strip, HOUGH_BLUR_KERNEL, HOUGH_BLUR_SIGMA)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp       = 1,
        minDist  = HOUGH_MIN_DIST,
        param1   = HOUGH_PARAM1,
        param2   = HOUGH_PARAM2,
        minRadius= HOUGH_MIN_RADIUS,
        maxRadius= HOUGH_MAX_RADIUS,
    )

    if circles is None:
        log.warning(f"[Hough] Nenhum círculo em [{x_min}:{x_max}, {y_min}:{y_max}]")
        return []

    result = []
    for cx, cy, r in np.round(circles[0]).astype(int):
        result.append((int(cx) + x_min, int(cy) + y_min, int(r)))

    log.debug(f"[Hough] bloco [{x_min}:{x_max}]: {len(result)} bolhas")
    return result


# ─── 3. Calibrar colunas ──────────────────────────────────────────────────────

def calibrar_colunas(bolhas: list[tuple[int, int, int]]) -> list[float]:
    """
    Dado conjunto de bolhas de um bloco, retorna os N_ALTERNATIVAS centros X
    das colunas (A, B, C, D, E) ordenados da esquerda para a direita.
    """
    if len(bolhas) < N_ALTERNATIVAS:
        raise ValueError(f"Bolhas insuficientes para calibrar colunas: {len(bolhas)}")

    xs = [float(cx) for cx, cy, r in bolhas]
    return _kmeans_1d(xs, N_ALTERNATIVAS)


# ─── 4. Calibrar linhas ───────────────────────────────────────────────────────

def calibrar_linhas(bolhas: list[tuple[int, int, int]]) -> tuple[float, float]:
    """
    Estima a posição Y da primeira questão (oy) e o espaçamento vertical (lg)
    a partir das bolhas detectadas pelo Hough.

    Retorna (oy, labelsGap).
    """
    if len(bolhas) < 3:
        raise ValueError(f"Bolhas insuficientes para calibrar linhas: {len(bolhas)}")

    ys       = [float(cy) for cx, cy, r in bolhas]
    # Número de linhas a estimar: limitado pelas bolhas disponíveis
    n_det    = max(3, min(len(bolhas) // 3, N_QUESTOES_POR_BLOCO))
    row_ctrs = _kmeans_1d(ys, n_det)

    if len(row_ctrs) < 2:
        raise ValueError("Linhas insuficientes para estimar labelsGap.")

    diffs = [row_ctrs[i + 1] - row_ctrs[i] for i in range(len(row_ctrs) - 1)]
    lg    = float(np.median(diffs))
    oy    = float(row_ctrs[0])          # centro da primeira bolha detectada

    log.debug(f"[Linhas] oy={round(oy)} lg={round(lg, 1)} ({n_det} linhas detectadas)")
    return oy, lg


# ─── 5. Ler bloco ─────────────────────────────────────────────────────────────

def _fill_mean(gray: np.ndarray, cx: int, cy: int) -> float:
    """
    Mede a intensidade média central da bolha em (cx, cy).
    Usa margem interna para evitar contaminação das bordas.
    """
    r  = FILL_RADIUS
    m  = max(1, int(r * FILL_MARGIN_FRAC))
    h, w = gray.shape
    y0, y1 = max(0, cy - r + m), min(h, cy + r - m)
    x0, x1 = max(0, cx - r + m), min(w, cx + r - m)
    roi = gray[y0:y1, x0:x1]
    return float(cv2.mean(roi)[0]) if roi.size > 0 else 255.0


def ler_bloco(
    gray: np.ndarray,
    col_centers: list[float],
    oy: float,
    lg: float,
    q_inicio: int,
) -> dict[int, list[float]]:
    """
    Lê o fill de todas as N_QUESTOES_POR_BLOCO × N_ALTERNATIVAS posições.

    Retorna dict {numero_questao: [fill_A, fill_B, fill_C, fill_D, fill_E]}.
    """
    h, w    = gray.shape
    result  = {}

    for qi in range(N_QUESTOES_POR_BLOCO):
        y = int(round(oy + qi * lg))
        if y < 0 or y >= h:
            log.debug(f"[Bloco] Q{q_inicio+qi}: y={y} fora da imagem, parando")
            break

        vals = []
        for cx in col_centers:
            x = int(round(cx))
            if x < 0 or x >= w:
                vals.append(255.0)
            else:
                vals.append(_fill_mean(gray, x, y))

        result[q_inicio + qi] = vals

    return result


# ─── Threshold ────────────────────────────────────────────────────────────────

def _threshold_global(all_vals: list[float]) -> float:
    """Threshold global: maior jump no histograma ordenado (janela ±1)."""
    sv      = sorted(all_vals)
    max_j   = MIN_JUMP_GLOBAL
    thr     = 200.0
    for i in range(1, len(sv) - 1):
        j = sv[i + 1] - sv[i - 1]
        if j > max_j:
            max_j = j
            thr   = sv[i - 1] + j / 2
    return thr


def _threshold_local(q_vals: list[float], global_thr: float) -> float:
    """Threshold local: maior gap entre os N_ALTERNATIVAS valores de uma questão."""
    sv    = sorted(q_vals)
    max_j = MIN_JUMP_LOCAL
    thr   = global_thr
    for i in range(len(sv) - 1):
        j = sv[i + 1] - sv[i]
        if j > max_j:
            max_j = j
            thr   = sv[i] + j / 2
    return thr


# ─── 6. Detectar todos ────────────────────────────────────────────────────────

def detectar_todos(img: np.ndarray, dia: int = 1) -> dict[int, str]:
    """
    Detecta todas as respostas do cartão automaticamente, sem template.

    Parâmetros:
        img  — imagem alinhada (saída do loader)
        dia  — dia da prova (1, 2, ...); aplica offset de questões

    Retorna {numero_questao: letra} para as questões detectadas.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    h, w = gray.shape

    y_min = int(h * BOLHAS_Y_MIN_FRAC)
    y_max = int(h * BOLHAS_Y_MAX_FRAC)

    # Offset de questões por dia
    q_offset = (dia - 1) * N_BLOCOS * N_QUESTOES_POR_BLOCO

    # 1. Separadores
    seps = encontrar_separadores(gray, y_min, y_max)

    # 2–5. Por bloco
    todos_fills: dict[int, list[float]] = {}

    for bloco_idx in range(N_BLOCOS):
        x_min = seps[bloco_idx]
        x_max = seps[bloco_idx + 1]
        q_inicio = bloco_idx * N_QUESTOES_POR_BLOCO + 1 + q_offset

        bolhas = hough_bolhas(gray, x_min, x_max, y_min, y_max)

        if len(bolhas) < N_ALTERNATIVAS * 2:
            log.warning(
                f"[Bloco {bloco_idx+1}] Bolhas insuficientes ({len(bolhas)}), "
                "pulando bloco."
            )
            continue

        try:
            col_centers = calibrar_colunas(bolhas)
            oy, lg      = calibrar_linhas(bolhas)
        except ValueError as e:
            log.warning(f"[Bloco {bloco_idx+1}] Calibração falhou: {e}")
            continue

        fills = ler_bloco(gray, col_centers, oy, lg, q_inicio)
        todos_fills.update(fills)

        log.info(
            f"[Bloco {bloco_idx+1}] Q{q_inicio}-Q{q_inicio+N_QUESTOES_POR_BLOCO-1} "
            f"cols={[round(c) for c in col_centers]} "
            f"oy={round(oy)} lg={round(lg,1)}"
        )

    if not todos_fills:
        log.error("[AutoDetect] Nenhum bloco detectado.")
        return {}

    # Threshold global sobre todos os fills
    all_vals   = [v for vals in todos_fills.values() for v in vals]
    thr_global = _threshold_global(all_vals)
    log.info(f"[AutoDetect] global_thr={round(thr_global, 1)}")

    # Converter fills → respostas
    respostas: dict[int, str] = {}

    for questao, vals in sorted(todos_fills.items()):
        if min(vals) > MAX_UNMARKED_VAL:
            log.debug(f"Q{questao}: sem marcação (min={min(vals):.0f})")
            continue

        thr      = _threshold_local(vals, thr_global)
        marcadas = [i for i, v in enumerate(vals) if v < thr]

        if len(marcadas) == 1:
            respostas[questao] = ALTERNATIVAS[marcadas[0]]
        elif len(marcadas) > 1:
            # Dupla marcação: usar o mais escuro como resposta
            mais_escuro = min(marcadas, key=lambda i: vals[i])
            log.warning(
                f"Q{questao}: dupla marcação "
                f"({[ALTERNATIVAS[i] for i in marcadas]}) "
                f"→ usando {ALTERNATIVAS[mais_escuro]}"
            )
            respostas[questao] = ALTERNATIVAS[mais_escuro]
        else:
            log.warning(f"Q{questao}: sem marcação após threshold (vals={[round(v,1) for v in vals]})")

    total = N_BLOCOS * N_QUESTOES_POR_BLOCO
    log.info(f"[AutoDetect] {len(respostas)}/{total} respostas detectadas.")
    return respostas
