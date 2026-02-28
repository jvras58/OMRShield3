"""
tests/api/test_schemas.py — Testa os schemas Pydantic da API.

Verifica que os schemas aceitam dados válidos e rejeitam inválidos.
"""

import pytest
from pydantic import ValidationError

from src.api.cartao.schemas import (
    BatchEnqueueResponse,
    BatchItemResponse,
    BatchResponse,
    CartaoResponse,
    JobStatusResponse,
)


# ── CartaoResponse ────────────────────────────────────────────────────────────


class TestCartaoResponse:
    def test_criacao_minima(self):
        r = CartaoResponse(
            job_id="abc",
            status="ok",
            cpf=None,
            tentativas_cpf=1,
            total_questoes_detectadas=90,
            questoes_esperadas=90,
            respostas={1: "A"},
            avisos=[],
        )
        assert r.job_id == "abc"
        assert r.grid_image_b64 is None
        assert r.grid_url is None

    def test_com_grid_b64(self):
        r = CartaoResponse(
            job_id="j",
            status="ok",
            cpf="123",
            tentativas_cpf=1,
            total_questoes_detectadas=90,
            questoes_esperadas=90,
            respostas={},
            avisos=[],
            grid_image_b64="base64str",
            grid_url="/cartao/j/grid",
        )
        assert r.grid_image_b64 == "base64str"
        assert r.grid_url == "/cartao/j/grid"

    def test_faltando_campo_obrigatorio(self):
        with pytest.raises(ValidationError):
            CartaoResponse(status="ok")  # job_id e outros faltando

    def test_serializa_para_dict(self):
        r = CartaoResponse(
            job_id="x",
            status="parcial",
            cpf=None,
            tentativas_cpf=0,
            total_questoes_detectadas=0,
            questoes_esperadas=90,
            respostas={},
            avisos=["aviso1"],
        )
        d = r.model_dump()
        assert d["status"] == "parcial"
        assert d["avisos"] == ["aviso1"]


# ── BatchEnqueueResponse ──────────────────────────────────────────────────────


class TestBatchEnqueueResponse:
    def test_criacao(self):
        r = BatchEnqueueResponse(
            job_ids=["id1", "id2"],
            total=2,
            status_url_tpl="/cartao/{job_id}/status",
        )
        assert r.total == 2
        assert r.status == "enqueued"  # default

    def test_status_default_enqueued(self):
        r = BatchEnqueueResponse(job_ids=[], total=0, status_url_tpl="/x/{job_id}/s")
        assert r.status == "enqueued"


# ── JobStatusResponse ─────────────────────────────────────────────────────────


class TestJobStatusResponse:
    def test_criacao_pendente(self):
        r = JobStatusResponse(job_id="j", status="pending")
        assert r.respostas is None
        assert r.grid_url is None
        assert r.cpf is None

    def test_criacao_done(self):
        r = JobStatusResponse(
            job_id="j",
            status="done",
            respostas={1: "A"},
            cpf="000",
            avisos=[],
            grid_url="/cartao/j/grid",
        )
        assert r.status == "done"
        assert r.grid_url == "/cartao/j/grid"

    def test_criacao_failed(self):
        r = JobStatusResponse(job_id="j", status="failed", avisos=["erro"])
        assert r.status == "failed"
        assert r.avisos == ["erro"]


# ── BatchItemResponse ─────────────────────────────────────────────────────────


class TestBatchItemResponse:
    def test_criacao(self):
        r = BatchItemResponse(
            arquivo="foto.jpg",
            job_id="j1",
            status="ok",
            cpf="123",
            total_questoes_detectadas=90,
            respostas={1: "A"},
            avisos=[],
        )
        assert r.arquivo == "foto.jpg"
        assert r.grid_url is None

    def test_sem_job_id(self):
        r = BatchItemResponse(
            arquivo="f.jpg",
            job_id=None,
            status="falhou",
            cpf=None,
            total_questoes_detectadas=0,
            respostas={},
            avisos=["erro"],
        )
        assert r.job_id is None


# ── BatchResponse ─────────────────────────────────────────────────────────────


class TestBatchResponse:
    def test_criacao(self):
        item = BatchItemResponse(
            arquivo="a.jpg",
            job_id="j",
            status="ok",
            cpf=None,
            total_questoes_detectadas=0,
            respostas={},
            avisos=[],
        )
        r = BatchResponse(total_arquivos=1, processados=1, resultados=[item])
        assert r.total_arquivos == 1
        assert len(r.resultados) == 1
