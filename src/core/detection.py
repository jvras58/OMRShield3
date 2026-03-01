"""
core/detection.py — Detecção automática de bolhas sem template (OpenCV + KMeans).

Pipeline:
  1. encontrar_separadores()  → gaps brancos que dividem os N_BLOCOS
  2. hough_bolhas()           → HoughCircles por bloco → (cx, cy, r)
  3. calibrar_colunas()       → KMeans em X → posições das N_ALTERNATIVAS colunas
  4. calibrar_linhas()        → KMeans em Y → oy + labelsGap
  5. ler_bloco()              → mede fill em grid completo → {qi: [v0..v4]}
  6. detectar_todos()         → recorta cabeçalho, orquestra blocos, aplica threshold

Mudanças em relação à versão original:
  - detectar_todos() chama recortar_zona_bolhas() para trabalhar apenas na faixa
    de questões, eliminando BOLHAS_Y_MIN_FRAC como fração fixa no Hough.
  - encontrar_separadores() e hough_bolhas() agora recebem a imagem já recortada
    (coordenadas locais), sem necessidade de y_min/y_max absolutos.

Exporta:
  encontrar_separadores, hough_bolhas, calibrar_colunas, calibrar_linhas,
  ler_bloco, detectar_todos
"""

import logging

import cv2
import numpy as np
from sklearn.cluster import KMeans

from src.settings.config import settings

log = logging.getLogger(__name__)


# ── Clustering ────────────────────────────────────────────────────────────────


def _kmeans_1d(values: list[float], k: int) -> list[float]:
    """Retorna k centros ordenados via KMeans 1-D."""
    if len(values) < k:
        return sorted(values)

    arr = np.array(values).reshape(-1, 1)
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(arr)
    return sorted(float(c) for c in km.cluster_centers_.flatten())


# ── 1. Separadores ────────────────────────────────────────────────────────────


def encontrar_separadores(gray: np.ndarray) -> list[int]:
    """
    Detecta as posições X que separam os N_BLOCOS colunas de questões.

    Usa dois métodos em cascata:

    1. Gaps explícitos: detecta colunas com < 5% da altura em pixels escuros.
       Se encontrar exatamente N_BLOCOS-1 gaps internos com larguras uniformes
       (coeficiente de variação < 15%), usa esses pontos diretamente.

    2. Periodicidade + refinamento local: estima a largura esperada de cada
       bloco (w / N_BLOCOS) e para cada borda esperada busca o mínimo de
       pixels escuros numa janela de ±10% ao redor — isso encontra o centro
       do gap mesmo quando o gap é estreito (< SEP_MIN_GAP_PX) ou quando
       os blocos têm larguras levemente diferentes.

    O método 2 é muito mais robusto que threshold fixo porque não depende
    de um valor absoluto de pixels escuros — trabalha com a estrutura
    periódica do cartão.
    """
    h, w = gray.shape
    dark_per_col = (gray < settings.SEP_PIXEL_THR).sum(axis=0).astype(float)
    smooth = np.convolve(dark_per_col, np.ones(5) / 5, mode="same")

    # ── Método 1: gaps explícitos com threshold adaptativo ────────────────
    gap_thr = h * 0.05  # < 5% da altura = gap

    in_gap, gap_start = False, 0
    gaps: list[tuple[int, int]] = []
    for x, dark in enumerate(dark_per_col):
        if dark < gap_thr and not in_gap:
            in_gap, gap_start = True, x
        elif dark >= gap_thr and in_gap:
            in_gap = False
            if x - gap_start >= 4:
                gaps.append((gap_start, x))
    if in_gap and w - gap_start >= 4:
        gaps.append((gap_start, w))

    # Só considera gaps internos (não nas bordas)
    gaps_internos = [(s, e) for s, e in gaps if s > 10 and e < w - 10]
    midpoints = [(s + e) // 2 for s, e in gaps_internos]

    if len(midpoints) == settings.N_BLOCOS - 1:
        seps = [0] + midpoints + [w]
        widths = [seps[i + 1] - seps[i] for i in range(settings.N_BLOCOS)]
        cv = float(np.std(widths)) / float(np.mean(widths))
        if cv < 0.15:
            log.info(f"[Sep] Método gaps: {seps} (cv={cv:.3f})")
            return seps
        log.debug(
            f"[Sep] Método gaps: larguras irregulares (cv={cv:.3f}), usando periodicidade"
        )
    else:
        log.debug(
            f"[Sep] Método gaps: {len(midpoints)} gaps (esperado {settings.N_BLOCOS - 1}), usando periodicidade"
        )

    # ── Método 2: periodicidade + refinamento local ───────────────────────
    block_w = w / settings.N_BLOCOS
    win = max(4, int(block_w * 0.10))  # janela de busca: ±10% da largura do bloco

    seps = [0]
    for i in range(1, settings.N_BLOCOS):
        centro = int(round(i * block_w))
        lo = max(1, centro - win)
        hi = min(w - 1, centro + win)
        local_min = lo + int(np.argmin(smooth[lo:hi]))
        seps.append(local_min)
    seps.append(w)

    widths = [seps[i + 1] - seps[i] for i in range(settings.N_BLOCOS)]
    log.info(f"[Sep] Método periodicidade: {seps} widths={widths}")
    return seps


# ── 2. Hough por bloco ────────────────────────────────────────────────────────


def hough_bolhas(
    gray: np.ndarray,
    x_min: int,
    x_max: int,
) -> list[tuple[int, int, int]]:
    """
    Detecta círculos (bolhas) numa faixa vertical da imagem já recortada.

    Parâmetros:
        gray  — grayscale da zona de bolhas (sem cabeçalho)
        x_min — coluna inicial do bloco
        x_max — coluna final do bloco

    Retorna lista de (cx, cy, r) em coordenadas da imagem recortada.
    """
    strip = gray[:, x_min:x_max]
    blurred = cv2.GaussianBlur(
        strip,
        settings.HOUGH_BLUR_KERNEL,
        settings.HOUGH_BLUR_SIGMA,
    )

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=settings.HOUGH_MIN_DIST,
        param1=settings.HOUGH_PARAM1,
        param2=settings.HOUGH_PARAM2,
        minRadius=settings.HOUGH_MIN_RADIUS,
        maxRadius=settings.HOUGH_MAX_RADIUS,
    )

    if circles is None:
        log.warning(f"[Hough] Nenhum círculo em bloco x=[{x_min}:{x_max}]")
        return []

    result = []
    for cx, cy, r in np.round(circles[0]).astype(int):
        result.append((int(cx) + x_min, int(cy), int(r)))

    log.debug(f"[Hough] bloco [{x_min}:{x_max}]: {len(result)} bolhas")
    return result


# ── 3. Calibrar colunas ───────────────────────────────────────────────────────


def calibrar_colunas(bolhas: list[tuple[int, int, int]]) -> list[float]:
    """Retorna os N_ALTERNATIVAS centros X das colunas ordenados."""
    if len(bolhas) < settings.N_ALTERNATIVAS:
        raise ValueError(f"Bolhas insuficientes para calibrar colunas: {len(bolhas)}")

    xs = [float(cx) for cx, cy, r in bolhas]
    return _kmeans_1d(xs, settings.N_ALTERNATIVAS)


# ── 4. Calibrar linhas ────────────────────────────────────────────────────────


def calibrar_linhas(
    bolhas: list[tuple[int, int, int]], h_recorte: int = 0
) -> tuple[float, float]:
    """
    Estima oy (Y da primeira questão) e lg (espaçamento entre linhas).

    Estratégia em cascata:

    1. KMeans com exatamente N_QUESTOES_POR_BLOCO clusters — ideal quando
       o Hough detectou bolhas em todas (ou quase todas) as linhas.
       Valida que o lg resultante é plausível (entre 50% e 150% do esperado).

    2. KMeans com o máximo de clusters possível (< N_Q) — quando há bolhas
       insuficientes mas ainda dá para estimar o espaçamento por interpolação.

    3. Fallback uniforme — divide h_recorte em N_Q partes iguais.

    CORREÇÃO em relação à versão anterior:
      A versão anterior usava n_det = len(bolhas) // 3, o que resultava em
      11 clusters para 34 bolhas (bloco 1) em vez de 15 — gerando lg errado
      e grid deslocado. Agora sempre tenta N_Q clusters primeiro.
    """
    n_q = settings.N_QUESTOES_POR_BLOCO
    lg_esperado = (h_recorte / (n_q + 1)) if h_recorte > 0 else 25.0
    lg_min = lg_esperado * 0.5
    lg_max = lg_esperado * 1.5

    if len(bolhas) < 2:
        raise ValueError(f"Bolhas insuficientes para calibrar linhas: {len(bolhas)}")

    ys = [float(cy) for _, cy, _ in bolhas]

    def _kmeans_e_valida(n: int) -> tuple[float, float] | None:
        ctrs = _kmeans_1d(ys, n)
        if len(ctrs) < 2:
            return None
        diffs = [ctrs[i + 1] - ctrs[i] for i in range(len(ctrs) - 1)]
        lg = float(np.median(diffs))
        # Valida apenas se temos referência de h_recorte
        if h_recorte > 0 and not (lg_min <= lg <= lg_max):
            return None
        return float(ctrs[0]), lg

    # 1. Ideal: N_Q clusters
    if len(bolhas) >= n_q:
        result = _kmeans_e_valida(n_q)
        if result:
            log.debug(f"[Linhas] KMeans({n_q}): oy={result[0]:.0f} lg={result[1]:.1f}")
            return result

    # 2. Máximo possível de clusters
    for n in range(min(len(bolhas), n_q - 1), 1, -1):
        result = _kmeans_e_valida(n)
        if result:
            log.debug(
                f"[Linhas] KMeans({n}) fallback: oy={result[0]:.0f} lg={result[1]:.1f}"
            )
            return result

    # 3. Fallback uniforme
    log.warning("[Linhas] Fallback uniforme")
    lg = lg_esperado if lg_esperado > 0 else 25.0
    oy = lg * 0.8
    return oy, lg


# ── 5. Ler bloco ──────────────────────────────────────────────────────────────


def _fill_mean(gray: np.ndarray, cx: int, cy: int) -> float:
    """Mede a intensidade média central da bolha em (cx, cy)."""
    r = settings.FILL_RADIUS
    m = max(1, int(r * settings.FILL_MARGIN_FRAC))
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
    Retorna {numero_questao: [fill_A, fill_B, fill_C, fill_D, fill_E]}.
    """
    h, w = gray.shape
    result = {}

    for qi in range(settings.N_QUESTOES_POR_BLOCO):
        y = int(round(oy + qi * lg))
        if y < 0 or y >= h:
            log.debug(f"[Bloco] Q{q_inicio + qi}: y={y} fora da imagem, parando")
            break

        vals = []
        for cx in col_centers:
            x = int(round(cx))
            vals.append(_fill_mean(gray, x, y) if 0 <= x < w else 255.0)

        result[q_inicio + qi] = vals

    return result


# ── Threshold ─────────────────────────────────────────────────────────────────


def _threshold_global(all_vals: list[float]) -> float:
    """Threshold global: maior jump no histograma ordenado (janela ±1)."""
    sv = sorted(all_vals)
    max_j = settings.MIN_JUMP_GLOBAL
    thr = 200.0
    for i in range(1, len(sv) - 1):
        j = sv[i + 1] - sv[i - 1]
        if j > max_j:
            max_j = j
            thr = sv[i - 1] + j / 2
    return thr


def _threshold_local(q_vals: list[float], global_thr: float) -> float:
    """Threshold local: maior gap entre os N_ALTERNATIVAS valores de uma questão."""
    sv = sorted(q_vals)
    max_j = settings.MIN_JUMP_LOCAL
    thr = global_thr
    for i in range(len(sv) - 1):
        j = sv[i + 1] - sv[i]
        if j > max_j:
            max_j = j
            thr = sv[i] + j / 2
    return thr


# ── 6. Detectar todos ─────────────────────────────────────────────────────────


def detectar_todos(img: np.ndarray, dia: int = 1) -> dict[int, str]:
    """
    Detecta todas as respostas do cartão automaticamente, sem template.

    Parâmetros:
        img — imagem alinhada (saída de core.alignment.alinhar),
              dimensões PAGE_WIDTH × PAGE_HEIGHT.
        dia — dia da prova (1, 2, ...); aplica offset de questões.

    O cabeçalho é removido dinamicamente antes do processamento.

    Retorna {numero_questao: letra} para as questões detectadas.
    """
    from src.core.alignment import recortar_zona_bolhas

    # ── Recorta o cabeçalho ────────────────────────────────────────────────
    zona, _y_offset = recortar_zona_bolhas(img)

    gray = cv2.cvtColor(zona, cv2.COLOR_BGR2GRAY) if zona.ndim == 3 else zona.copy()
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    q_offset = (dia - 1) * settings.QUESTOES_POR_DIA

    # ── Detecta separadores na zona já recortada ───────────────────────────
    seps = encontrar_separadores(gray)

    todos_fills: dict[int, list[float]] = {}

    for bloco_idx in range(settings.N_BLOCOS):
        x_min = seps[bloco_idx]
        x_max = seps[bloco_idx + 1]
        q_inicio = bloco_idx * settings.N_QUESTOES_POR_BLOCO + 1 + q_offset

        bolhas = hough_bolhas(gray, x_min, x_max)

        if len(bolhas) < settings.N_ALTERNATIVAS * 2:
            log.warning(
                f"[Bloco {bloco_idx + 1}] Bolhas insuficientes ({len(bolhas)}), "
                "pulando bloco."
            )
            continue

        try:
            col_centers = calibrar_colunas(bolhas)
            oy, lg = calibrar_linhas(bolhas, h_recorte=gray.shape[0])
        except ValueError as e:
            log.warning(f"[Bloco {bloco_idx + 1}] Calibração falhou: {e}")
            continue

        fills = ler_bloco(gray, col_centers, oy, lg, q_inicio)
        todos_fills.update(fills)

        log.info(
            f"[Bloco {bloco_idx + 1}] Q{q_inicio}-"
            f"Q{q_inicio + settings.N_QUESTOES_POR_BLOCO - 1} "
            f"cols={[round(c) for c in col_centers]} "
            f"oy={round(oy)} lg={round(lg, 1)}"
        )

    if not todos_fills:
        log.error("[AutoDetect] Nenhum bloco detectado.")
        return {}

    all_vals = [v for vals in todos_fills.values() for v in vals]
    thr_global = _threshold_global(all_vals)
    log.info(f"[AutoDetect] global_thr={round(thr_global, 1)}")

    respostas: dict[int, str] = {}

    for questao, vals in sorted(todos_fills.items()):
        if min(vals) > settings.MAX_UNMARKED_VAL:
            log.debug(f"Q{questao}: sem marcação (min={min(vals):.0f})")
            continue

        thr = _threshold_local(vals, thr_global)
        marcadas = [i for i, v in enumerate(vals) if v < thr]

        if len(marcadas) == 1:
            respostas[questao] = settings.ALTERNATIVAS[marcadas[0]]
        elif len(marcadas) > 1:
            mais_escuro = min(marcadas, key=lambda i: vals[i])
            log.warning(
                f"Q{questao}: dupla marcação "
                f"({[settings.ALTERNATIVAS[i] for i in marcadas]}) "
                f"→ usando {settings.ALTERNATIVAS[mais_escuro]}"
            )
            respostas[questao] = settings.ALTERNATIVAS[mais_escuro]
        else:
            log.warning(
                f"Q{questao}: sem marcação após threshold "
                f"(vals={[round(v, 1) for v in vals]})"
            )

    total = settings.N_BLOCOS * settings.N_QUESTOES_POR_BLOCO
    log.info(f"[AutoDetect] {len(respostas)}/{total} respostas detectadas.")
    return respostas
