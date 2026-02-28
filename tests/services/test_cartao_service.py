"""
tests/services/test_cartao_service.py — Testa ExtratorCartao.

As funções pesadas de OpenCV (carregar_imagem_bytes, extrair_cpf, detectar_todos)
são mockadas para que os testes rodem sem imagens reais.

Cenários:
  processar_bytes OK       — CPF + 90 questões → Status.OK
  processar_bytes PARCIAL  — CPF + menos questões → Status.PARCIAL
  processar_bytes sem CPF  — sem CPF + 90 questões → Status.PARCIAL
  processar_bytes falha    — imagem inválida (carregar_imagem_bytes levanta)
  processar_arquivo OK     — mesmo pipeline via arquivo
  processar_arquivo falha  — arquivo inválido
"""

from unittest.mock import patch

import numpy as np

from src.models.resultado import Status
from src.services.cartao_service import ExtratorCartao
from src.settings.config import settings

_IMG = np.ones((1000, 800, 3), dtype=np.uint8) * 200
_RESPOSTAS_COMPLETAS = {i: "A" for i in range(1, settings.QUESTOES_POR_DIA + 1)}
_RESPOSTAS_PARCIAIS = {i: "B" for i in range(1, 46)}


def _extrator():
    return ExtratorCartao()


# ── processar_bytes ───────────────────────────────────────────────────────────


@patch("src.services.cartao_service.detectar_todos", return_value=_RESPOSTAS_COMPLETAS)
@patch("src.services.cartao_service.extrair_cpf", return_value=("12345678900", 1))
@patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG)
def test_processar_bytes_ok(mock_load, mock_cpf, mock_det):
    r = _extrator().processar_bytes(b"img", dia=1)
    assert r.status == Status.OK
    assert r.cpf == "12345678900"
    assert r.total_questoes_detectadas == settings.QUESTOES_POR_DIA
    assert r.avisos == []


@patch("src.services.cartao_service.detectar_todos", return_value=_RESPOSTAS_PARCIAIS)
@patch("src.services.cartao_service.extrair_cpf", return_value=("12345678900", 1))
@patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG)
def test_processar_bytes_parcial_pouco_questoes(mock_load, mock_cpf, mock_det):
    r = _extrator().processar_bytes(b"img", dia=1)
    assert r.status == Status.PARCIAL
    assert r.total_questoes_detectadas == 45
    assert any("questoes" in a for a in r.avisos)


@patch("src.services.cartao_service.detectar_todos", return_value=_RESPOSTAS_COMPLETAS)
@patch("src.services.cartao_service.extrair_cpf", return_value=(None, 3))
@patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG)
def test_processar_bytes_parcial_sem_cpf(mock_load, mock_cpf, mock_det):
    r = _extrator().processar_bytes(b"img", dia=1)
    assert r.status == Status.PARCIAL
    assert r.cpf is None
    assert any("CPF" in a for a in r.avisos)


@patch("src.services.cartao_service.detectar_todos", return_value={})
@patch("src.services.cartao_service.extrair_cpf", return_value=(None, 0))
@patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG)
def test_processar_bytes_falhou_sem_nada(mock_load, mock_cpf, mock_det):
    r = _extrator().processar_bytes(b"img", dia=1)
    assert r.status == Status.FALHOU
    assert r.total_questoes_detectadas == 0


@patch(
    "src.services.cartao_service.carregar_imagem_bytes",
    side_effect=ValueError("Não foi possível decodificar a imagem."),
)
def test_processar_bytes_imagem_invalida(mock_load):
    r = _extrator().processar_bytes(b"invalido", dia=1)
    assert r.status == Status.FALHOU
    assert any("possível" in a for a in r.avisos)


def test_processar_bytes_img_alinhada_preservada():
    """img_alinhada deve ser a imagem devolvida por carregar_imagem_bytes."""
    with (
        patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG),
        patch(
            "src.services.cartao_service.extrair_cpf", return_value=("00000000000", 1)
        ),
        patch(
            "src.services.cartao_service.detectar_todos",
            return_value=_RESPOSTAS_COMPLETAS,
        ),
    ):
        r = _extrator().processar_bytes(b"img")
        assert r.img_alinhada is _IMG


def test_processar_bytes_tentativas_cpf_registradas():
    with (
        patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG),
        patch("src.services.cartao_service.extrair_cpf", return_value=(None, 3)),
        patch("src.services.cartao_service.detectar_todos", return_value={}),
    ):
        r = _extrator().processar_bytes(b"img")
        assert r.tentativas_cpf == 3


def test_processar_bytes_dia_2_passado_ao_detectar():
    """dia deve ser repassado para detectar_todos."""
    with (
        patch("src.services.cartao_service.carregar_imagem_bytes", return_value=_IMG),
        patch("src.services.cartao_service.extrair_cpf", return_value=(None, 0)),
        patch("src.services.cartao_service.detectar_todos") as mock_det,
    ):
        mock_det.return_value = {}
        _extrator().processar_bytes(b"img", dia=2)
        _, kwargs = mock_det.call_args
        assert kwargs.get("dia") == 2


# ── processar_arquivo ─────────────────────────────────────────────────────────


@patch("src.services.cartao_service.detectar_todos", return_value=_RESPOSTAS_COMPLETAS)
@patch("src.services.cartao_service.extrair_cpf", return_value=("11122233344", 1))
@patch("src.services.cartao_service.carregar_imagem", return_value=_IMG)
def test_processar_arquivo_ok(mock_load, mock_cpf, mock_det):
    r = _extrator().processar_arquivo("caminho/falso.jpg", dia=1)
    assert r.status == Status.OK


@patch(
    "src.services.cartao_service.carregar_imagem",
    side_effect=ValueError("Não foi possível abrir 'caminho/falso.jpg'."),
)
def test_processar_arquivo_inexistente(mock_load):
    r = _extrator().processar_arquivo("caminho/falso.jpg", dia=1)
    assert r.status == Status.FALHOU
    assert len(r.avisos) > 0
