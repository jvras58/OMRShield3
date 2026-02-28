"""
tests/api/test_cartao.py — Testa o endpoint POST /cartao.

Cenários:
  - Resultado OK: 90 questões, CPF detectado
  - Resultado PARCIAL: menos questões, sem CPF
  - Resultado FALHOU: 0 questões, sem imagem alinhada
  - Parâmetro dia=2
  - incluir_grid=true → grid_image_b64 presente
  - incluir_grid=false (default) → grid_image_b64 ausente
  - Arquivo com content-type inválido ainda é aceito (API não valida mime)
"""

import base64


# ── Helpers ───────────────────────────────────────────────────────────────────


def _post_cartao(client, img_bytes, dia=1, incluir_grid=False):
    return client.post(
        "/cartao",
        data={"dia": str(dia), "incluir_grid": str(incluir_grid).lower()},
        files={"file": ("cartao.jpg", img_bytes, "image/jpeg")},
    )


# ── Status OK ─────────────────────────────────────────────────────────────────


def test_cartao_retorna_200(client, imagem_bytes):
    r = _post_cartao(client, imagem_bytes)
    assert r.status_code == 200


def test_cartao_ok_campos_obrigatorios(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes).json()
    assert "job_id" in data
    assert "status" in data
    assert "cpf" in data
    assert "respostas" in data
    assert "avisos" in data
    assert "total_questoes_detectadas" in data
    assert "questoes_esperadas" in data


def test_cartao_ok_status_valor(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes).json()
    assert data["status"] == "ok"


def test_cartao_ok_cpf(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes).json()
    assert data["cpf"] == "12345678900"


def test_cartao_ok_90_questoes(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes).json()
    assert data["total_questoes_detectadas"] == 90
    assert len(data["respostas"]) == 90


def test_cartao_ok_sem_avisos(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes).json()
    assert data["avisos"] == []


def test_cartao_ok_job_id_e_grid_url(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes).json()
    job_id = data["job_id"]
    assert job_id  # não vazio
    assert data["grid_url"] == f"/cartao/{job_id}/grid"


def test_cartao_sem_incluir_grid_nao_tem_b64(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes, incluir_grid=False).json()
    assert data.get("grid_image_b64") is None


def test_cartao_com_incluir_grid_retorna_b64(client, imagem_bytes):
    data = _post_cartao(client, imagem_bytes, incluir_grid=True).json()
    b64 = data.get("grid_image_b64")
    assert b64 is not None
    # deve ser base64 válido
    decoded = base64.b64decode(b64)
    assert len(decoded) > 0


# ── Parâmetro dia ─────────────────────────────────────────────────────────────


def test_cartao_dia_2(client, imagem_bytes):
    r = _post_cartao(client, imagem_bytes, dia=2)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cartao_dia_invalido_retorna_422(client, imagem_bytes):
    """dia=0 viola ge=1 → FastAPI retorna 422 Unprocessable Entity."""
    r = _post_cartao(client, imagem_bytes, dia=0)
    assert r.status_code == 422


# ── Resultado PARCIAL ─────────────────────────────────────────────────────────


def test_cartao_parcial_status(client_parcial, imagem_bytes):
    data = _post_cartao(client_parcial, imagem_bytes).json()
    assert data["status"] == "parcial"


def test_cartao_parcial_questoes_detectadas(client_parcial, imagem_bytes):
    data = _post_cartao(client_parcial, imagem_bytes).json()
    assert data["total_questoes_detectadas"] == 45


def test_cartao_parcial_sem_cpf(client_parcial, imagem_bytes):
    data = _post_cartao(client_parcial, imagem_bytes).json()
    assert data["cpf"] is None


def test_cartao_parcial_tem_avisos(client_parcial, imagem_bytes):
    data = _post_cartao(client_parcial, imagem_bytes).json()
    assert len(data["avisos"]) > 0


def test_cartao_parcial_tem_grid_url(client_parcial, imagem_bytes):
    """Resultado parcial ainda tem img_alinhada → grid_url deve existir."""
    data = _post_cartao(client_parcial, imagem_bytes).json()
    assert data["grid_url"] is not None


# ── Resultado FALHOU ──────────────────────────────────────────────────────────


def test_cartao_falhou_status(client_falho, imagem_bytes):
    data = _post_cartao(client_falho, imagem_bytes).json()
    assert data["status"] == "falhou"


def test_cartao_falhou_zero_questoes(client_falho, imagem_bytes):
    data = _post_cartao(client_falho, imagem_bytes).json()
    assert data["total_questoes_detectadas"] == 0
    assert data["respostas"] == {}


def test_cartao_falhou_sem_grid_url(client_falho, imagem_bytes):
    """Sem img_alinhada, grid_url deve ser None."""
    data = _post_cartao(client_falho, imagem_bytes).json()
    assert data["grid_url"] is None


# ── Arquivo ausente ───────────────────────────────────────────────────────────


def test_cartao_sem_arquivo_retorna_422(client):
    r = client.post("/cartao", data={"dia": "1"})
    assert r.status_code == 422
