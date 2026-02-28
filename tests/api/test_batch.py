"""
tests/api/test_batch.py — Testa o endpoint POST /cartao/batch.

O endpoint enfileira arquivos no broker e retorna imediatamente.
Cenários:
  - 1 arquivo enfileirado
  - 2 arquivos enfileirados
  - Sem arquivos → 422
  - dia inválido → 422
  - Resposta contém job_ids, total e status='enqueued'
  - status_url_tpl presente e correto
"""


def _post_batch(client, img_bytes, n_files=1, dia=1, nomes=None):
    if nomes is None:
        nomes = [f"cartao_{i}.jpg" for i in range(n_files)]
    files = [("files", (nome, img_bytes, "image/jpeg")) for nome in nomes]
    return client.post("/cartao/batch", data={"dia": str(dia)}, files=files)


# ── 1 arquivo ─────────────────────────────────────────────────────────────────


def test_batch_1_arquivo_retorna_200(client, imagem_bytes):
    r = _post_batch(client, imagem_bytes, n_files=1)
    assert r.status_code == 200


def test_batch_1_arquivo_campos_obrigatorios(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=1).json()
    assert "job_ids" in data
    assert "total" in data
    assert "status" in data
    assert "status_url_tpl" in data


def test_batch_1_arquivo_status_enqueued(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=1).json()
    assert data["status"] == "enqueued"


def test_batch_1_arquivo_total_correto(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=1).json()
    assert data["total"] == 1
    assert len(data["job_ids"]) == 1


def test_batch_1_arquivo_job_id_nao_vazio(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=1).json()
    assert data["job_ids"][0]


def test_batch_status_url_template(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=1).json()
    assert "{job_id}" in data["status_url_tpl"]


# ── 2 arquivos ────────────────────────────────────────────────────────────────


def test_batch_2_arquivos_total_correto(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=2).json()
    assert data["total"] == 2
    assert len(data["job_ids"]) == 2


def test_batch_2_arquivos_job_ids_distintos(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=2).json()
    assert data["job_ids"][0] != data["job_ids"][1]


def test_batch_3_arquivos(client, imagem_bytes):
    data = _post_batch(client, imagem_bytes, n_files=3).json()
    assert data["total"] == 3
    assert len(set(data["job_ids"])) == 3  # todos distintos


# ── Parâmetro dia ─────────────────────────────────────────────────────────────


def test_batch_dia_2(client, imagem_bytes):
    r = _post_batch(client, imagem_bytes, n_files=1, dia=2)
    assert r.status_code == 200


def test_batch_dia_invalido_422(client, imagem_bytes):
    r = _post_batch(client, imagem_bytes, n_files=1, dia=0)
    assert r.status_code == 422


# ── Sem arquivos ──────────────────────────────────────────────────────────────


def test_batch_sem_arquivos_422(client):
    r = client.post("/cartao/batch", data={"dia": "1"})
    assert r.status_code == 422


# ── Broker é chamado ──────────────────────────────────────────────────────────


def test_batch_broker_chamado_uma_vez(client, mock_broker, imagem_bytes):
    _post_batch(client, imagem_bytes, n_files=1)
    mock_broker.publish.assert_called_once()


def test_batch_broker_chamado_n_vezes(client, mock_broker, imagem_bytes):
    n = 3
    _post_batch(client, imagem_bytes, n_files=n)
    assert mock_broker.publish.call_count == n
