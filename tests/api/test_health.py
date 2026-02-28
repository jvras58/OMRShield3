"""
tests/api/test_health.py — Testa o endpoint GET /health.

O health check agora vive na raiz da aplicação (fora do router /cartao)
 e não exige autenticação; deve responder 200 mesmo quando o token
 estiver configurado ou ausente.
"""


def test_health_retorna_status_ok(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_content_type_json(client):
    r = client.get("/")
    assert "application/json" in r.headers["content-type"]


def test_health_nao_exige_token(client_com_auth):
    """Mesmo com API_TOKEN configurado, não deve pedir autenticação."""
    from src.settings.config import settings

    original = settings.API_TOKEN
    settings.API_TOKEN = "qualquer"
    try:
        r = client_com_auth.get("/")
        assert r.status_code == 200
    finally:
        settings.API_TOKEN = original
