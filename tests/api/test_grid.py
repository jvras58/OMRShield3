"""
tests/api/test_grid.py — Testa GET /cartao/{job_id}/grid.

Cenários:
  - job_id inexistente       → 404
  - job_id processado        → 200 JPEG
  - content-type correto
  - Bytes recebidos são JPEG válido
"""

import numpy as np

def _salvar_job_no_cache(fake_cache, job_id: str):
    img = np.ones((1000, 800, 3), dtype=np.uint8) * 180
    respostas = {i: "A" for i in range(1, 91)}
    fake_cache.set(job_id, img, respostas, dia=1, cpf="00000000000")


# ── job_id inexistente ────────────────────────────────────────────────────────


def test_grid_job_inexistente_404(client):
    r = client.get("/cartao/id-fantasma/grid")
    assert r.status_code == 404


# ── job_id existente ──────────────────────────────────────────────────────────


def test_grid_retorna_200(client, fake_cache):
    _salvar_job_no_cache(fake_cache, "job-grid-ok")
    r = client.get("/cartao/job-grid-ok/grid")
    assert r.status_code == 200


def test_grid_content_type_jpeg(client, fake_cache):
    _salvar_job_no_cache(fake_cache, "job-ct")
    r = client.get("/cartao/job-ct/grid")
    assert r.headers["content-type"] == "image/jpeg"


def test_grid_conteudo_nao_vazio(client, fake_cache):
    _salvar_job_no_cache(fake_cache, "job-sz")
    r = client.get("/cartao/job-sz/grid")
    assert len(r.content) > 0


def test_grid_bytes_sao_jpeg_valido(client, fake_cache):
    """Verifica assinatura JPEG (bytes FF D8 FF no início)."""
    _salvar_job_no_cache(fake_cache, "job-magic")
    r = client.get("/cartao/job-magic/grid")
    assert r.content[:3] == b"\xff\xd8\xff"


def test_grid_acessivel_apos_post_cartao(client, imagem_bytes):
    """Fluxo integrado: POST /cartao → GET /cartao/{job_id}/grid."""
    post = client.post(
        "/cartao",
        data={"dia": "1"},
        files={"file": ("c.jpg", imagem_bytes, "image/jpeg")},
    )
    assert post.status_code == 200
    job_id = post.json()["job_id"]

    r = client.get(f"/cartao/{job_id}/grid")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
