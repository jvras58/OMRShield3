"""
core/quality.py — Validação de qualidade antes do processamento OMR.

Rejeita imagens que não tenham condições mínimas de ser processadas,
retornando mensagens claras em português para o usuário final.

Uso típico:
    from src.core.quality import validar_imagem, QualidadeInsuficiente

    try:
        validar_imagem(img)          # levanta QualidadeInsuficiente se ruim
    except QualidadeInsuficiente as e:
        return {"erro": str(e), "problemas": e.problemas}

    resultado = processar(img)       # só chega aqui se passou na validação
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from src.core.alignment import _detectar_marcadores, _order_points

log = logging.getLogger(__name__)

# ── Thresholds (todos justificados por testes empíricos) ──────────────────────
MIN_PIXELS = 500_000  # ~700×700px — abaixo disso detecção falha
MIN_COBERTURA = 0.35  # cartão deve ocupar ≥35% da imagem
MAX_DESVIO_ANGULO = 25  # °  — inclinação máxima aceitável
MIN_ASPECT = 1.10  # proporção altura/largura mínima do cartão
MAX_ASPECT = 1.80  # proporção altura/largura máxima
MIN_NITIDEZ = 30  # variância Laplaciana — abaixo = borrado
MIN_LUMINANCIA = 40  # média cinza — abaixo = muito escuro
MAX_LUMINANCIA = 230  # média cinza — acima = muito claro/reflexo


# ── Exceção pública ───────────────────────────────────────────────────────────


class QualidadeInsuficiente(Exception):
    """
    Levantada quando a imagem não atende aos critérios mínimos de qualidade.

    Atributos:
        problemas — lista de strings descrevendo cada problema encontrado,
                    em linguagem direta para o usuário final.
    """

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = problemas
        super().__init__(self._resumo())

    def _resumo(self) -> str:
        if len(self.problemas) == 1:
            return self.problemas[0]
        itens = "\n".join(f"  • {p}" for p in self.problemas)
        return f"A imagem apresenta {len(self.problemas)} problemas:\n{itens}"


# ── Checagens individuais ─────────────────────────────────────────────────────


def _checar_resolucao(img: np.ndarray) -> str | None:
    h, w = img.shape[:2]
    if w * h < MIN_PIXELS:
        return (
            f"Resolução muito baixa ({w}×{h}px). "
            "Use a câmera traseira e fotografe mais perto."
        )
    return None


def _checar_nitidez(gray: np.ndarray) -> str | None:
    nitidez = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if nitidez < MIN_NITIDEZ:
        return (
            f"Imagem borrada (nitidez={nitidez:.0f}). "
            "Mantenha o celular firme e aguarde o foco automático antes de fotografar."
        )
    return None


def _checar_luminancia(gray: np.ndarray) -> str | None:
    lum = float(gray.mean())
    if lum < MIN_LUMINANCIA:
        return (
            f"Imagem muito escura (luminância={lum:.0f}). "
            "Fotografe em local bem iluminado, preferencialmente com luz natural."
        )
    if lum > MAX_LUMINANCIA:
        return (
            f"Imagem com excesso de luz ou reflexo (luminância={lum:.0f}). "
            "Evite luz direta sobre o cartão e reflexos de flash."
        )
    return None


def _checar_marcadores(img: np.ndarray) -> tuple[dict | None, str | None]:
    """Retorna (marcadores, erro_str). Se erro_str não é None, marcadores é None."""
    try:
        m = _detectar_marcadores(img)
        return m, None
    except ValueError:
        return None, (
            "Não foi possível encontrar os 4 marcadores quadrados dos cantos do cartão. "
            "Verifique se:\n"
            "  • O cartão está completamente dentro do enquadramento\n"
            "  • Os cantos não estão dobrados, cobertos ou com sombra\n"
            "  • O fundo não é preto ou muito escuro"
        )


def _checar_geometria(marcadores: dict, img_shape: tuple[int, int]) -> list[str]:
    """Verifica inclinação, proporção e cobertura do cartão na imagem."""
    h, w = img_shape
    problemas = []

    pts = np.array(
        [marcadores["TL"], marcadores["TR"], marcadores["BR"], marcadores["BL"]],
        dtype="float32",
    )
    rect = _order_points(pts)  # TL, TR, BR, BL

    # Ângulos nos 4 cantos
    def _angulo(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        v1, v2 = a - b, c - b
        cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))

    angulos = [
        _angulo(rect[3], rect[0], rect[1]),  # TL
        _angulo(rect[0], rect[1], rect[2]),  # TR
        _angulo(rect[1], rect[2], rect[3]),  # BR
        _angulo(rect[2], rect[3], rect[0]),  # BL
    ]
    desvio = max(abs(a - 90) for a in angulos)
    if desvio > MAX_DESVIO_ANGULO:
        problemas.append(
            f"Cartão inclinado ({desvio:.0f}° de desvio). "
            "Fotografe de frente e paralelo ao cartão, sem ângulo lateral."
        )

    # Proporção altura/largura
    larg = (np.linalg.norm(rect[1] - rect[0]) + np.linalg.norm(rect[2] - rect[3])) / 2
    alt = (np.linalg.norm(rect[3] - rect[0]) + np.linalg.norm(rect[2] - rect[1])) / 2
    aspect = alt / max(larg, 1)
    if not (MIN_ASPECT < aspect < MAX_ASPECT):
        problemas.append(
            f"Proporção do cartão inesperada ({aspect:.2f}:1). "
            "Certifique-se de que o cartão inteiro está enquadrado sem deformação."
        )

    # Cobertura da imagem
    area_quad = float(cv2.contourArea(rect))
    cobertura = area_quad / (w * h)
    if cobertura < MIN_COBERTURA:
        problemas.append(
            f"Cartão muito pequeno na imagem ({cobertura * 100:.0f}% da área). "
            "Aproxime mais a câmera até o cartão preencher a maior parte da tela."
        )

    return problemas


# ── API pública ───────────────────────────────────────────────────────────────


@dataclass
class ResultadoQualidade:
    """Resultado detalhado da validação de qualidade."""

    ok: bool
    problemas: list[str] = field(default_factory=list)
    nitidez: float = 0.0
    luminancia: float = 0.0
    cobertura: float = 0.0
    desvio_angulo: float = 0.0


def checar_qualidade(img: np.ndarray) -> ResultadoQualidade:
    """
    Avalia a qualidade da imagem sem levantar exceção.
    Útil para retornar JSON de diagnóstico ao frontend.
    """
    problemas: list[str] = []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()

    # Métricas brutas
    nitidez = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    luminancia = float(gray.mean())

    # Checagens em ordem de diagnóstico
    if err := _checar_resolucao(img):
        problemas.append(err)
        # Sem resolução mínima, as demais checagens são irrelevantes
        return ResultadoQualidade(
            ok=False, problemas=problemas, nitidez=nitidez, luminancia=luminancia
        )

    if err := _checar_nitidez(gray):
        problemas.append(err)

    if err := _checar_luminancia(gray):
        problemas.append(err)

    marcadores, err_marc = _checar_marcadores(img)
    if err_marc:
        problemas.append(err_marc)
        return ResultadoQualidade(
            ok=False, problemas=problemas, nitidez=nitidez, luminancia=luminancia
        )

    erros_geo = _checar_geometria(marcadores, (h, w))
    problemas.extend(erros_geo)

    # Calcular métricas para o resultado (mesmo que ok)
    pts = np.array(
        [marcadores["TL"], marcadores["TR"], marcadores["BR"], marcadores["BL"]],
        dtype="float32",
    )
    rect = _order_points(pts)
    cobertura = float(cv2.contourArea(rect)) / (w * h)

    def _angulo(a, b, c):
        v1, v2 = a - b, c - b
        cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))

    angulos = [
        _angulo(rect[3], rect[0], rect[1]),
        _angulo(rect[0], rect[1], rect[2]),
        _angulo(rect[1], rect[2], rect[3]),
        _angulo(rect[2], rect[3], rect[0]),
    ]
    desvio = max(abs(a - 90) for a in angulos)

    ok = len(problemas) == 0
    if ok:
        log.info(
            f"[Qualidade] OK — nitidez={nitidez:.0f} lum={luminancia:.0f} "
            f"cobertura={cobertura * 100:.0f}% desvio={desvio:.1f}°"
        )
    else:
        log.warning(f"[Qualidade] {len(problemas)} problema(s): {problemas}")

    return ResultadoQualidade(
        ok=ok,
        problemas=problemas,
        nitidez=nitidez,
        luminancia=luminancia,
        cobertura=cobertura,
        desvio_angulo=desvio,
    )


def validar_imagem(img: np.ndarray) -> None:
    """
    Valida a imagem e levanta QualidadeInsuficiente se ela não for processável.

    Chamada antes de alinhar() no pipeline principal.
    """
    resultado = checar_qualidade(img)
    if not resultado.ok:
        raise QualidadeInsuficiente(resultado.problemas)
