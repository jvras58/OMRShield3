"""
tests/core/test_detection.py — Testa as funções do pipeline de detecção OpenCV.

Estratégia:
  - Funções puras (calibrar_colunas, calibrar_linhas, ler_bloco) são testadas
    com dados sintéticos gerados numericamente.
  - encontrar_separadores é testado com imagens grayscale sintéticas simples.
  - detectar_todos é testado com imagem vazia (retorna {}) para garantir
    que o pipeline não crasha com entrada inválida.

Não depende de imagens reais de cartão.
"""

import numpy as np
import pytest

from src.core.detection import (
    calibrar_colunas,
    calibrar_linhas,
    detectar_todos,
    encontrar_separadores,
    ler_bloco,
)
from src.settings.config import settings


# ── Auxiliares ────────────────────────────────────────────────────────────────


def _imagem_com_separadores(
    w: int = 600, h: int = 300, n_blocos: int = 6, espessura_gap: int = 8
) -> np.ndarray:
    """
    Imagem grayscale sintética com N_BLOCOS-1 gaps brancos verticais
    separando regiões escuras — simula o layout de um cartão real.
    """
    img = np.full((h, w), 30, dtype=np.uint8)  # fundo escuro
    block_w = w // n_blocos
    for i in range(1, n_blocos):
        x = i * block_w
        img[:, x - espessura_gap // 2 : x + espessura_gap // 2] = 255
    return img


def _bolhas_grid(
    n_alt: int = 5,
    n_q: int = 15,
    x0: float = 50.0,
    dx: float = 40.0,
    y0: float = 50.0,
    dy: float = 20.0,
    r: int = 10,
) -> list[tuple[int, int, int]]:
    """
    Cria uma grade sintética de bolhas com posições conhecidas.
    n_alt colunas, n_q linhas.
    """
    bolhas = []
    for ai in range(n_alt):
        for qi in range(n_q):
            cx = int(round(x0 + ai * dx))
            cy = int(round(y0 + qi * dy))
            bolhas.append((cx, cy, r))
    return bolhas


# ── encontrar_separadores ─────────────────────────────────────────────────────


class TestEncontrarSeparadores:
    def test_retorna_n_blocos_mais_um(self):
        img = _imagem_com_separadores()
        seps = encontrar_separadores(img, 0, img.shape[0])
        assert len(seps) == settings.N_BLOCOS + 1

    def test_primeiro_e_ultimo(self):
        img = _imagem_com_separadores(w=600, h=200)
        seps = encontrar_separadores(img, 0, img.shape[0])
        assert seps[0] == 0
        assert seps[-1] == img.shape[1]

    def test_seps_sao_crescentes(self):
        img = _imagem_com_separadores()
        seps = encontrar_separadores(img, 0, img.shape[0])
        assert all(seps[i] < seps[i + 1] for i in range(len(seps) - 1))

    def test_fallback_divisao_uniforme(self):
        """Imagem totalmente escura (sem gaps) usa divisão uniforme."""
        img = np.zeros((200, 600), dtype=np.uint8)  # tudo escuro, sem gaps
        seps = encontrar_separadores(img, 0, img.shape[0])
        assert len(seps) == settings.N_BLOCOS + 1
        assert seps[0] == 0
        assert seps[-1] == img.shape[1]

    def test_largura_de_blocos_aproximadamente_uniforme(self):
        """Com gaps igualmente espaçados, blocos devem ser aproximadamente iguais."""
        img = _imagem_com_separadores(w=600, h=200)
        seps = encontrar_separadores(img, 0, img.shape[0])
        larguras = [seps[i + 1] - seps[i] for i in range(settings.N_BLOCOS)]
        media = sum(larguras) / len(larguras)
        for larg in larguras:
            assert abs(larg - media) < media * 0.3  # dentro de 30% da média

    def test_y_min_e_y_max_limitam_regiao(self):
        """Separadores devem ser detectados apenas na faixa y_min:y_max."""
        w, h = 600, 400
        img = _imagem_com_separadores(w=w, h=h)
        seps_full = encontrar_separadores(img, 0, h)
        seps_crop = encontrar_separadores(img, h // 2, h)
        # ambos devem ter N_BLOCOS+1 elementos
        assert len(seps_full) == len(seps_crop) == settings.N_BLOCOS + 1


# ── calibrar_colunas ──────────────────────────────────────────────────────────


class TestCalibrarColunas:
    def test_retorna_n_alternativas_colunas(self):
        bolhas = _bolhas_grid()
        cols = calibrar_colunas(bolhas)
        assert len(cols) == settings.N_ALTERNATIVAS

    def test_colunas_sao_crescentes(self):
        bolhas = _bolhas_grid()
        cols = calibrar_colunas(bolhas)
        assert all(cols[i] < cols[i + 1] for i in range(len(cols) - 1))

    def test_colunas_proximas_das_esperadas(self):
        x0, dx = 50.0, 40.0
        bolhas = _bolhas_grid(x0=x0, dx=dx)
        cols = calibrar_colunas(bolhas)
        esperadas = [x0 + i * dx for i in range(settings.N_ALTERNATIVAS)]
        for c, e in zip(cols, esperadas):
            assert abs(c - e) < 5.0  # tolerância de 5 px

    def test_bolhas_insuficientes_levanta_value_error(self):
        bolhas = [(10, 10, 5), (20, 10, 5)]  # menos que N_ALTERNATIVAS
        with pytest.raises(ValueError, match="Bolhas insuficientes"):
            calibrar_colunas(bolhas)

    def test_bolhas_exatamente_n_alternativas(self):
        """Com exatamente N_ALTERNATIVAS bolhas, não deve levantar."""
        bolhas = [(i * 40, 50, 10) for i in range(settings.N_ALTERNATIVAS)]
        cols = calibrar_colunas(bolhas)
        assert len(cols) == settings.N_ALTERNATIVAS


# ── calibrar_linhas ───────────────────────────────────────────────────────────


class TestCalibrarLinhas:
    def test_retorna_oy_e_lg(self):
        bolhas = _bolhas_grid()
        result = calibrar_linhas(bolhas)
        assert len(result) == 2

    def test_oy_proximo_do_esperado(self):
        y0, dy = 50.0, 20.0
        bolhas = _bolhas_grid(y0=y0, dy=dy)
        oy, _ = calibrar_linhas(bolhas)
        assert abs(oy - y0) < 5.0

    def test_lg_proximo_do_espamento(self):
        y0, dy = 50.0, 20.0
        bolhas = _bolhas_grid(y0=y0, dy=dy)
        _, lg = calibrar_linhas(bolhas)
        assert abs(lg - dy) < 5.0

    def test_bolhas_insuficientes_levanta_value_error(self):
        with pytest.raises(ValueError, match="Bolhas insuficientes"):
            calibrar_linhas([(10, 10, 5), (20, 20, 5)])  # apenas 2

    def test_oy_e_lg_sao_float(self):
        bolhas = _bolhas_grid()
        oy, lg = calibrar_linhas(bolhas)
        assert isinstance(oy, float)
        assert isinstance(lg, float)

    def test_lg_positivo(self):
        bolhas = _bolhas_grid(dy=25.0)
        _, lg = calibrar_linhas(bolhas)
        assert lg > 0


# ── ler_bloco ─────────────────────────────────────────────────────────────────


class TestLerBloco:
    def test_retorna_n_questoes_por_bloco(self):
        gray = np.ones((500, 300), dtype=np.uint8) * 200
        bolhas = _bolhas_grid(n_alt=5, n_q=15, x0=10, dx=50, y0=10, dy=30)
        cols = calibrar_colunas(bolhas)
        oy, lg = calibrar_linhas(bolhas)
        result = ler_bloco(gray, cols, oy, lg, q_inicio=1)
        assert len(result) == settings.N_QUESTOES_POR_BLOCO

    def test_cada_questao_tem_n_alternativas_valores(self):
        gray = np.ones((500, 300), dtype=np.uint8) * 200
        bolhas = _bolhas_grid(n_alt=5, n_q=15, x0=10, dx=50, y0=10, dy=30)
        cols = calibrar_colunas(bolhas)
        oy, lg = calibrar_linhas(bolhas)
        result = ler_bloco(gray, cols, oy, lg, q_inicio=1)
        for vals in result.values():
            assert len(vals) == settings.N_ALTERNATIVAS

    def test_valores_sao_float(self):
        gray = np.ones((500, 300), dtype=np.uint8) * 200
        bolhas = _bolhas_grid(x0=10, dx=50, y0=10, dy=30)
        cols = calibrar_colunas(bolhas)
        oy, lg = calibrar_linhas(bolhas)
        result = ler_bloco(gray, cols, oy, lg, q_inicio=1)
        for vals in result.values():
            assert all(isinstance(v, float) for v in vals)

    def test_q_inicio_define_numero_das_questoes(self):
        gray = np.ones((500, 300), dtype=np.uint8) * 200
        bolhas = _bolhas_grid(x0=10, dx=50, y0=10, dy=30)
        cols = calibrar_colunas(bolhas)
        oy, lg = calibrar_linhas(bolhas)
        q_inicio = 46
        result = ler_bloco(gray, cols, oy, lg, q_inicio=q_inicio)
        qs = sorted(result.keys())
        assert qs[0] == q_inicio

    def test_imagem_branca_retorna_valores_altos(self):
        """Bolhas em imagem branca → fill deve ser próximo de 255 (não marcadas)."""
        gray = np.full((500, 300), 255, dtype=np.uint8)
        bolhas = _bolhas_grid(x0=10, dx=50, y0=10, dy=30)
        cols = calibrar_colunas(bolhas)
        oy, lg = calibrar_linhas(bolhas)
        result = ler_bloco(gray, cols, oy, lg, q_inicio=1)
        for vals in result.values():
            assert all(v > 200 for v in vals)


# ── detectar_todos ────────────────────────────────────────────────────────────


class TestDetectarTodos:
    def test_imagem_branca_retorna_dict(self):
        """Imagem totalmente branca — sem bolhas detectáveis → retorna {}."""
        img = np.full((1000, 800, 3), 255, dtype=np.uint8)
        result = detectar_todos(img, dia=1)
        assert isinstance(result, dict)

    def test_nao_crasha_com_imagem_escura(self):
        """Imagem preta — sem features → retorna {} sem exception."""
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        result = detectar_todos(img, dia=1)
        assert isinstance(result, dict)

    def test_nao_crasha_com_imagem_cinza(self):
        """Imagem cinza uniforme → fallback gracioso."""
        img = np.full((1000, 800, 3), 128, dtype=np.uint8)
        result = detectar_todos(img, dia=1)
        assert isinstance(result, dict)

    def test_aceita_imagem_grayscale(self):
        """detectar_todos deve aceitar imagem 2D (grayscale) sem crasha."""
        img = np.full((1000, 800), 200, dtype=np.uint8)
        result = detectar_todos(img, dia=1)
        assert isinstance(result, dict)

    def test_resultado_letras_validas(self):
        """Todas as letras retornadas devem estar em A-E."""
        img = np.full((1000, 800, 3), 200, dtype=np.uint8)
        result = detectar_todos(img, dia=1)
        for letra in result.values():
            assert letra in settings.ALTERNATIVAS

    def test_questoes_positivas(self):
        """Números de questão devem ser >= 1."""
        img = np.full((1000, 800, 3), 200, dtype=np.uint8)
        result = detectar_todos(img, dia=1)
        for q in result.keys():
            assert q >= 1

    def test_dia_2_questoes_offset(self):
        """Com dia=2 as questões detectadas (se houver) devem ter offset correto."""
        img = np.full((1000, 800, 3), 200, dtype=np.uint8)
        result = detectar_todos(img, dia=2)
        if result:
            offset = (2 - 1) * settings.QUESTOES_POR_DIA
            for q in result.keys():
                assert q > offset
