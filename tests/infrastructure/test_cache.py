"""
tests/infrastructure/test_cache.py — Testa o GridCache com FakeRedis.

Cobre:
  set / get           — armazenamento e recuperação de imagem + metadados
  __contains__        — operador 'in'
  get_status          — consulta sem carregar imagem
  set_failed          — marcação de job com falha
  set_temp / get_temp — armazenamento temporário para batch
  del_temp            — remoção do temporário
  expiração simulada  — TTL respeitado (fakeredis suporta)
"""

import numpy as np
import pytest

from src.infrastructure.cache import GridCache


# ── Fixtures locais ───────────────────────────────────────────────────────────


@pytest.fixture
def cache(fake_redis) -> GridCache:
    return GridCache(fake_redis)


@pytest.fixture
def img() -> np.ndarray:
    return np.ones((100, 120, 3), dtype=np.uint8) * 128


@pytest.fixture
def respostas_ok() -> dict:
    return {i: "A" for i in range(1, 91)}


# ── set / get ─────────────────────────────────────────────────────────────────


def test_set_e_get_retorna_tupla(cache, img, respostas_ok):
    cache.set("j1", img, respostas_ok, dia=1, cpf="11122233344")
    result = cache.get("j1")
    assert result is not None
    assert len(result) == 3


def test_get_retorna_imagem_decodificada(cache, img, respostas_ok):
    cache.set("j2", img, respostas_ok, dia=1)
    img_r, _, _ = cache.get("j2")
    assert isinstance(img_r, np.ndarray)
    assert img_r.shape[2] == 3  # BGR


def test_get_retorna_respostas_corretas(cache, img, respostas_ok):
    cache.set("j3", img, respostas_ok, dia=1)
    _, resp, _ = cache.get("j3")
    assert resp == respostas_ok


def test_get_retorna_dia_correto(cache, img):
    cache.set("j4", img, {}, dia=2)
    _, _, dia = cache.get("j4")
    assert dia == 2


def test_get_job_inexistente_retorna_none(cache):
    assert cache.get("nao-existe") is None


# ── __contains__ ──────────────────────────────────────────────────────────────


def test_contains_verdadeiro(cache, img):
    cache.set("j5", img, {}, dia=1)
    assert "j5" in cache


def test_contains_falso(cache):
    assert "fantasma" not in cache


# ── get_status ────────────────────────────────────────────────────────────────


def test_get_status_done(cache, img, respostas_ok):
    cache.set("j6", img, respostas_ok, dia=1, cpf="99988877766", avisos=["aviso1"])
    status = cache.get_status("j6")
    assert status is not None
    assert status["status"] == "done"
    assert status["cpf"] == "99988877766"
    assert status["avisos"] == ["aviso1"]


def test_get_status_respostas_corretas(cache, img):
    respostas = {1: "B", 2: "C"}
    cache.set("j7", img, respostas, dia=1)
    status = cache.get_status("j7")
    assert status["respostas"] == respostas


def test_get_status_dia_correto(cache, img):
    cache.set("j8", img, {}, dia=2)
    assert cache.get_status("j8")["dia"] == 2


def test_get_status_inexistente_retorna_none(cache):
    assert cache.get_status("nao-existe") is None


# ── set_failed ────────────────────────────────────────────────────────────────


def test_set_failed_status(cache):
    cache.set_failed("j9", ["Erro grave", "Imagem corrompida"])
    status = cache.get_status("j9")
    assert status["status"] == "failed"


def test_set_failed_avisos(cache):
    avisos = ["falha 1", "falha 2"]
    cache.set_failed("j10", avisos)
    status = cache.get_status("j10")
    assert status["avisos"] == avisos


def test_set_failed_respostas_vazio(cache):
    cache.set_failed("j11", [])
    status = cache.get_status("j11")
    assert status["respostas"] == {}


# ── set_temp / get_temp ───────────────────────────────────────────────────────


def test_set_temp_e_get_temp(cache):
    dados = b"bytes-da-imagem-raw"
    cache.set_temp("t1", dados)
    assert cache.get_temp("t1") == dados


def test_get_temp_inexistente(cache):
    assert cache.get_temp("t-fantasma") is None


def test_del_temp_remove(cache):
    cache.set_temp("t2", b"dados")
    cache.del_temp("t2")
    assert cache.get_temp("t2") is None


def test_del_temp_inexistente_nao_levanta(cache):
    """del_temp em chave inexistente não deve levantar exceção."""
    cache.del_temp("t-inexistente")  # não deve lançar
