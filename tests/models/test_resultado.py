"""
tests/models/test_resultado.py — Testa os modelos de domínio.

Cobre:
  Status          — valores do enum
  Resultado       — dataclass com valores default
  CartaoJob       — modelo Pydantic para fila
"""

import pytest

from src.models.resultado import CartaoJob, Resultado, Status


# ── Status ────────────────────────────────────────────────────────────────────


def test_status_valores():
    assert Status.OK.value == "ok"
    assert Status.PARCIAL.value == "parcial"
    assert Status.FALHOU.value == "falhou"


def test_status_membros():
    membros = {s.value for s in Status}
    assert membros == {"ok", "parcial", "falhou"}


# ── Resultado ─────────────────────────────────────────────────────────────────


def test_resultado_defaults():
    r = Resultado()
    assert r.cpf is None
    assert r.respostas == {}
    assert r.avisos == []
    assert r.status == Status.FALHOU
    assert r.tentativas_cpf == 0
    assert r.total_questoes_detectadas == 0
    assert r.img_alinhada is None


def test_resultado_com_valores():
    r = Resultado(
        cpf="12345678900",
        respostas={1: "A", 2: "B"},
        status=Status.OK,
        avisos=["aviso"],
        tentativas_cpf=2,
        total_questoes_detectadas=2,
    )
    assert r.cpf == "12345678900"
    assert r.respostas == {1: "A", 2: "B"}
    assert r.status == Status.OK
    assert r.avisos == ["aviso"]
    assert r.tentativas_cpf == 2
    assert r.total_questoes_detectadas == 2


def test_resultado_listas_independentes():
    """Duas instâncias não devem compartilhar listas (default_factory)."""
    r1 = Resultado()
    r2 = Resultado()
    r1.avisos.append("teste")
    assert r2.avisos == []


def test_resultado_dicts_independentes():
    r1 = Resultado()
    r2 = Resultado()
    r1.respostas[1] = "A"
    assert 1 not in r2.respostas


# ── CartaoJob ─────────────────────────────────────────────────────────────────


def test_cartao_job_criacao():
    job = CartaoJob(job_id="abc-123", dia=1, filename="cartao.jpg")
    assert job.job_id == "abc-123"
    assert job.dia == 1
    assert job.filename == "cartao.jpg"


def test_cartao_job_model_dump():
    job = CartaoJob(job_id="xyz", dia=2, filename="foto.png")
    d = job.model_dump()
    assert d == {"job_id": "xyz", "dia": 2, "filename": "foto.png"}


def test_cartao_job_validacao_dia_obrigatorio():
    with pytest.raises(Exception):
        CartaoJob(job_id="j", filename="f.jpg")  # dia ausente


def test_cartao_job_json_serializable():
    job = CartaoJob(job_id="j1", dia=1, filename="x.jpg")
    json_str = job.model_dump_json()
    assert "j1" in json_str
    assert "dia" in json_str
