"""
visualizer.py — Geração da imagem de debug com grid auto-detectado sobreposto.

Responsabilidade única: dado cartão alinhado + respostas detectadas,
produz imagem anotada (grid colorido + painel lateral de resumo).

Exporta:
  render_resultado(img, respostas, dia) → np.ndarray  (BGR)
  render_para_bytes(img, respostas, dia, fmt, max_w) → bytes  (JPEG/PNG)
  render_para_b64(img, respostas, dia, fmt, max_w)   → str    (base64)
"""

import base64
import logging
from typing import Literal

import cv2
import numpy as np

from src.auto_detect import (
    encontrar_separadores,
    hough_bolhas,
    calibrar_colunas,
    calibrar_linhas,
)
from src.config import (
    N_BLOCOS,
    N_QUESTOES_POR_BLOCO,
    N_ALTERNATIVAS,
    ALTERNATIVAS,
    BOLHAS_Y_MIN_FRAC,
    BOLHAS_Y_MAX_FRAC,
    FILL_RADIUS,
)

log = logging.getLogger(__name__)

# ── Constantes visuais ────────────────────────────────────────────────────────

COR_MARCADA  = (0, 220, 0)
COR_VAZIA    = (60, 60, 60)
COR_DUPLA    = (0, 80, 255)
COR_AUSENTE  = (0, 0, 220)
COR_SEP      = (0, 220, 255)
COR_DESTAQUE = (0, 220, 255)
COR_TEXTO    = (255, 255, 255)
COR_FUNDO    = (22, 22, 22)
PAINEL_W     = 340

QUESTOES_POR_DIA = N_BLOCOS * N_QUESTOES_POR_BLOCO


# ── Grid ──────────────────────────────────────────────────────────────────────

def _desenhar_grid(img: np.ndarray, respostas: dict, dia: int) -> np.ndarray:
    """Sobrepõe o grid auto-detectado na imagem, colorindo cada bolha."""
    out  = img.copy()
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    h, w = out.shape[:2]

    y_min = int(h * BOLHAS_Y_MIN_FRAC)
    y_max = int(h * BOLHAS_Y_MAX_FRAC)
    seps  = encontrar_separadores(gray, y_min, y_max)

    q_offset = (dia - 1) * QUESTOES_POR_DIA

    for bloco_idx in range(N_BLOCOS):
        x_min    = seps[bloco_idx]
        x_max    = seps[bloco_idx + 1]
        q_inicio = bloco_idx * N_QUESTOES_POR_BLOCO + 1 + q_offset

        # Linha do separador
        cv2.line(out, (x_min, y_min), (x_min, y_max), COR_SEP, 1)

        bolhas = hough_bolhas(gray, x_min, x_max, y_min, y_max)
        if len(bolhas) < N_ALTERNATIVAS * 2:
            continue

        try:
            col_centers = calibrar_colunas(bolhas)
            oy, lg      = calibrar_linhas(bolhas)
        except ValueError:
            continue

        r = FILL_RADIUS

        # Rótulos das alternativas acima do bloco
        for ai, letra in enumerate(ALTERNATIVAS):
            x = int(round(col_centers[ai])) - 5
            cv2.putText(out, letra, (x, max(y_min - 4, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28, COR_DESTAQUE, 1)

        for qi in range(N_QUESTOES_POR_BLOCO):
            y       = int(round(oy + qi * lg))
            questao = q_inicio + qi
            resp    = respostas.get(questao)

            for ai, letra in enumerate(ALTERNATIVAS):
                x = int(round(col_centers[ai]))

                if resp is None:
                    cor, fill = COR_AUSENTE, False
                elif len(resp) > 1:
                    cor  = COR_DUPLA
                    fill = letra in resp
                elif letra == resp:
                    cor, fill = COR_MARCADA, True
                else:
                    cor, fill = COR_VAZIA, False

                m = 2
                cv2.rectangle(
                    out,
                    (x - r + m, y - r + m),
                    (x + r - m, y + r - m),
                    cor, -1 if fill else 1,
                )

            # Rótulo da questão à esquerda
            cv2.putText(
                out, f"Q{questao}",
                (max(x_min - 28, 0), y + r // 2 + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.28, COR_DESTAQUE, 1,
            )

    return out


# ── Painel lateral ────────────────────────────────────────────────────────────

def _fazer_painel(respostas: dict, dia: int, altura: int) -> np.ndarray:
    """Painel lateral com resumo estatístico e lista de respostas."""
    H = altura
    p = np.full((H, PAINEL_W, 3), COR_FUNDO, dtype=np.uint8)

    def t(y, txt, cor=COR_TEXTO, s=0.38, bold=False):
        if y < H - 5:
            cv2.putText(p, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, s, cor,
                        2 if bold else 1, cv2.LINE_AA)

    q_start  = 1 + (dia - 1) * QUESTOES_POR_DIA
    q_end    = q_start + QUESTOES_POR_DIA
    ausentes = [q for q in range(q_start, q_end) if q not in respostas]
    duplas   = {q: r for q, r in respostas.items() if len(r) > 1}

    t(28, f"AUTO-DETECT — DIA {dia}", COR_DESTAQUE, s=0.50, bold=True)
    t(55, f"Detectadas : {len(respostas)}/{QUESTOES_POR_DIA}",
      COR_MARCADA if len(respostas) == QUESTOES_POR_DIA else (0, 160, 255))
    t(76, f"Ausentes   : {len(ausentes)}", COR_AUSENTE if ausentes else COR_MARCADA)
    t(97, f"Duplas     : {len(duplas)}",   COR_DUPLA   if duplas   else COR_MARCADA)

    # Legenda
    t(128, "Legenda:", COR_DESTAQUE)
    cv2.rectangle(p, (10, 135), (22, 147), COR_MARCADA, -1)
    t(147, "  marcada",       COR_MARCADA)
    cv2.rectangle(p, (10, 154), (22, 166), COR_VAZIA, 1)
    t(167, "  vazia",         COR_VAZIA)
    cv2.rectangle(p, (10, 173), (22, 185), COR_AUSENTE, 1)
    t(187, "  sem marcacao",  COR_AUSENTE)
    cv2.rectangle(p, (10, 192), (22, 204), COR_DUPLA, -1)
    t(207, "  dupla",         COR_DUPLA)

    # Grid de respostas
    t(235, "Respostas:", COR_DESTAQUE)
    cols = 3
    cw   = PAINEL_W // cols
    y_ini, lh = 258, 18

    for i, q in enumerate(range(q_start, q_end)):
        col = i % cols
        row = i // cols
        x   = 8 + col * cw
        y   = y_ini + row * lh
        if y > H - 20:
            break
        resp = respostas.get(q, "?")
        cor  = (COR_MARCADA  if resp not in ("?",) and len(resp) == 1 else
                COR_DUPLA    if resp not in ("?",) and len(resp) > 1  else
                COR_AUSENTE)
        cv2.putText(p, f"Q{q:02d}:{resp}", (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.33, cor, 1, cv2.LINE_AA)

    # Avisos de ausentes
    if ausentes:
        y_aus = y_ini + ((QUESTOES_POR_DIA // cols) + 2) * lh
        y_aus = min(y_aus, H - 80)
        t(y_aus, "Ausentes:", COR_AUSENTE)
        aus_str = ", ".join(f"Q{q}" for q in ausentes[:20])
        if len(ausentes) > 20:
            aus_str += f"... +{len(ausentes) - 20}"
        for i in range(0, len(aus_str), 35):
            t(y_aus + 18 + (i // 35) * 16, aus_str[i:i + 35], COR_AUSENTE, s=0.33)

    return p


# ── API pública ───────────────────────────────────────────────────────────────

def render_resultado(
    img: np.ndarray,
    respostas: dict,
    dia: int = 1,
    max_w: int = 1400,
) -> np.ndarray:
    """
    Gera imagem anotada com grid + painel lateral.

    Retorna array BGR pronto para salvar ou encodar.
    """
    img_grid = _desenhar_grid(img, respostas, dia)
    painel   = _fazer_painel(respostas, dia, img.shape[0])
    frame    = np.hstack([img_grid, painel])

    fh, fw = frame.shape[:2]
    if fw > max_w:
        s     = max_w / fw
        frame = cv2.resize(frame, (int(fw * s), int(fh * s)))

    return frame


def render_para_bytes(
    img: np.ndarray,
    respostas: dict,
    dia: int = 1,
    fmt: Literal["jpeg", "png"] = "jpeg",
    max_w: int = 1400,
) -> bytes:
    """Renderiza e encoda para bytes JPEG ou PNG."""
    frame = render_resultado(img, respostas, dia, max_w)
    ext   = ".jpg" if fmt == "jpeg" else ".png"
    ok, buf = cv2.imencode(ext, frame)
    if not ok:
        raise RuntimeError("Falha ao encodar imagem")
    return buf.tobytes()


def render_para_b64(
    img: np.ndarray,
    respostas: dict,
    dia: int = 1,
    fmt: Literal["jpeg", "png"] = "jpeg",
    max_w: int = 1400,
) -> str:
    """Renderiza e retorna string base64 (sem prefixo data:image)."""
    raw = render_para_bytes(img, respostas, dia, fmt, max_w)
    return base64.b64encode(raw).decode("ascii")
