"""
tests/api/test_status.py — Testa GET /cartao/{job_id}/status.

Cenários:
  - job_id inexistente  → 404
  - job_id com temp     → status='pending'
  - job_id processado   → status='done' com respostas e grid_url
  - job_id com falha    → status='failed'
"""

import numpy as np


# ── job_id desconhecido ───────────────────────────────────────────────────────


def test_status_job_id_inexistente_404(client):
    r = client.get("/cartao/nao-existe-esse-id/status")
    assert r.status_code == 404


# ── job_id com imagem temporária (pending) ────────────────────────────────────


def test_status_pending(client, fake_cache):
    fake_cache.set_temp("job-pendente", b"bytes-fake")
    r = client.get("/cartao/job-pendente/status")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_status_pending_campos(client, fake_cache):
    fake_cache.set_temp("job-p2", b"dados")
    data = client.get("/cartao/job-p2/status").json()
    assert data["job_id"] == "job-p2"
    assert data["status"] == "pending"


# ── job_id processado (done) ──────────────────────────────────────────────────


def test_status_done(client, fake_cache):
    img = np.ones((100, 100, 3), dtype=np.uint8) * 200
    respostas = {i: "A" for i in range(1, 91)}
    fake_cache.set("job-done", img, respostas, dia=1, cpf="12345678900")

    data = client.get("/cartao/job-done/status").json()
    assert data["status"] == "done"
    assert data["grid_url"] == "/cartao/job-done/grid"


def test_status_done_respostas(client, fake_cache):
    img = np.ones((100, 100, 3), dtype=np.uint8) * 200
    respostas = {i: "B" for i in range(1, 16)}
    fake_cache.set("job-res", img, respostas, dia=1)

    data = client.get("/cartao/job-res/status").json()
    assert data["respostas"] is not None
    assert len(data["respostas"]) == 15


def test_status_done_cpf(client, fake_cache):
    img = np.ones((100, 100, 3), dtype=np.uint8) * 200
    fake_cache.set("job-cpf", img, {1: "C"}, dia=1, cpf="98765432100")

    data = client.get("/cartao/job-cpf/status").json()
    assert data["cpf"] == "98765432100"


# ── job_id com falha ──────────────────────────────────────────────────────────


def test_status_failed(client, fake_cache):
    fake_cache.set_failed("job-fail", ["Erro ao processar imagem."])
    data = client.get("/cartao/job-fail/status").json()
    assert data["status"] == "failed"
    assert data["grid_url"] is None
