"""
tests/core/test_alignment.py — Testa as novas funções de alignment.py.

Cobre:
  detectar_y_bolhas()    — deve retornar fração válida [0,1]; fallback em casos ruins
  recortar_zona_bolhas() — deve retornar recorte menor que a original + y_offset correto
"""

import numpy as np

from src.core.alignment import detectar_y_bolhas, recortar_zona_bolhas
from src.settings.config import settings


# ── Fixtures de imagens sintéticas ────────────────────────────────────────────


def _img_com_linha_separadora(
    w: int = 1000,
    h: int = 1400,
    y_sep_frac: float = 0.65,
    espessura: int = 5,
) -> np.ndarray:
    """
    Imagem BGR cinza clara com uma linha horizontal escura em y_sep_frac.
    Simula o separador cabeçalho/questões impresso no cartão.
    """
    img = np.full((h, w, 3), 220, dtype=np.uint8)
    y_sep = int(h * y_sep_frac)
    img[y_sep : y_sep + espessura, :] = 20  # linha escura
    return img


def _img_uniforme(valor: int = 200, w: int = 1000, h: int = 1400) -> np.ndarray:
    """Imagem BGR uniforme — sem linha separadora."""
    return np.full((h, w, 3), valor, dtype=np.uint8)


# ── detectar_y_bolhas ─────────────────────────────────────────────────────────


class TestDetectarYBolhas:
    def test_retorna_float(self):
        img = _img_com_linha_separadora()
        frac = detectar_y_bolhas(img)
        assert isinstance(frac, float)

    def test_resultado_entre_0_e_1(self):
        img = _img_com_linha_separadora()
        frac = detectar_y_bolhas(img)
        assert 0.0 <= frac <= 1.0

    def test_detecta_separador_na_regiao_certa(self):
        """A fração detectada deve ser próxima da linha real (+2% de margem)."""
        y_sep_frac = 0.65
        img = _img_com_linha_separadora(y_sep_frac=y_sep_frac)
        frac = detectar_y_bolhas(img)
        # Tolerância: ±5% (a margem de +2% e arredondamentos)
        assert abs(frac - y_sep_frac) < 0.08

    def test_imagem_branca_retorna_fallback(self):
        """Sem linha escura, deve retornar o fallback configurado."""
        img = _img_uniforme(valor=255)
        frac = detectar_y_bolhas(img)
        assert frac == settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    def test_imagem_preta_retorna_fallback(self):
        """Imagem toda preta — pico não confiável, retorna fallback."""
        img = _img_uniforme(valor=0)
        frac = detectar_y_bolhas(img)
        assert frac == settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    def test_aceita_grayscale(self):
        """Deve funcionar com imagem 2D (grayscale)."""
        img = np.full((1400, 1000), 200, dtype=np.uint8)
        frac = detectar_y_bolhas(img)
        assert 0.0 <= frac <= 1.0

    def test_separador_em_40_pct(self):
        """Separador abaixo de HEADER_SEARCH_Y_MIN_FRAC deve usar fallback."""
        # Linha fora da janela de busca (muito acima)
        img = _img_com_linha_separadora(y_sep_frac=0.20)
        frac = detectar_y_bolhas(img)
        # Fora da janela → fallback
        assert frac == settings.BOLHAS_Y_MIN_FRAC_FALLBACK

    def test_separador_em_75_pct(self):
        """Separador dentro da janela de busca deve ser detectado."""
        img = _img_com_linha_separadora(y_sep_frac=0.72)
        frac = detectar_y_bolhas(img)
        assert abs(frac - 0.72) < 0.08


# ── recortar_zona_bolhas ──────────────────────────────────────────────────────


class TestRecortarZonaBolhas:
    def test_retorna_tupla_dois_elementos(self):
        img = _img_com_linha_separadora()
        result = recortar_zona_bolhas(img)
        assert len(result) == 2

    def test_recorte_e_ndarray(self):
        img = _img_com_linha_separadora()
        recorte, _ = recortar_zona_bolhas(img)
        assert isinstance(recorte, np.ndarray)

    def test_y_offset_e_inteiro(self):
        img = _img_com_linha_separadora()
        _, y_offset = recortar_zona_bolhas(img)
        assert isinstance(y_offset, int)

    def test_recorte_menor_que_original(self):
        """O recorte deve ser mais curto que a imagem completa."""
        img = _img_com_linha_separadora()
        recorte, _ = recortar_zona_bolhas(img)
        assert recorte.shape[0] < img.shape[0]

    def test_largura_preservada(self):
        """A largura do recorte deve ser igual à original."""
        img = _img_com_linha_separadora()
        recorte, _ = recortar_zona_bolhas(img)
        assert recorte.shape[1] == img.shape[1]

    def test_canais_preservados(self):
        """BGR deve ser mantido (3 canais)."""
        img = _img_com_linha_separadora()
        recorte, _ = recortar_zona_bolhas(img)
        assert recorte.ndim == 3
        assert recorte.shape[2] == 3

    def test_y_offset_positivo(self):
        """y_offset deve ser > 0 (o recorte começa depois do topo)."""
        img = _img_com_linha_separadora()
        _, y_offset = recortar_zona_bolhas(img)
        assert y_offset > 0

    def test_y_offset_consistente_com_recorte(self):
        """img[y_offset:] deve ter a mesma altura que o recorte."""
        img = _img_com_linha_separadora()
        recorte, y_offset = recortar_zona_bolhas(img)
        esperado = img.shape[0] - y_offset
        assert abs(recorte.shape[0] - esperado) <= 2  # tolerância de 2px

    def test_nao_crasha_imagem_uniforme(self):
        """Mesmo sem separador claro, não deve lançar exceção."""
        img = _img_uniforme()
        recorte, y_offset = recortar_zona_bolhas(img)
        assert isinstance(recorte, np.ndarray)
        assert y_offset >= 0
