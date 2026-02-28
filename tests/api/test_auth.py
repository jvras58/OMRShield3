"""
tests/api/test_auth.py — Testa o mecanismo de autenticação via X-Verify-Token.

A aplicação usa APIKeyHeader para ler o header.
O health check foi movido para fora do router /cartao e agora está aberto
(sem exigir token). Os testes abaixo se concentram nos endpoints protegidos
relacionados a cartão.
"""

from src.settings.config import settings


def test_health_pode_ser_acessado_sem_token(client, client_com_auth):
    """GET / deve ser 200 independentemente da configuração de token."""
    original = settings.API_TOKEN
    settings.API_TOKEN = "qualquer"
    try:
        r1 = client.get("/")
        r2 = client_com_auth.get("/")
        assert r1.status_code == 200
        assert r2.status_code == 200
    finally:
        settings.API_TOKEN = original


# --- helpers para requests de cartão -------------------------------


def _post_cartao(client, token=None, imagem_bytes=None):
    headers = {}
    if token is not None:
        headers["X-Verify-Token"] = token
    data = {"dia": "1"}
    files = {}
    if imagem_bytes is not None:
        files = {"file": ("cartao.jpg", imagem_bytes, "image/jpeg")}
    return client.post("/cartao", headers=headers, data=data, files=files)


# ── Sem token algum ───────────────────────────────────────────────────────────


def test_sem_token_api_token_vazio_retorna_401(client_com_auth):
    """Sem header e API_TOKEN vazio → 401 no POST /cartao."""
    original = settings.API_TOKEN
    settings.API_TOKEN = ""
    try:
        r = _post_cartao(client_com_auth, token=None, imagem_bytes=b"x")
        assert r.status_code == 401
    finally:
        settings.API_TOKEN = original


def test_sem_token_com_api_token_configurado_retorna_4xx(client_com_auth):
    """Sem header e API_TOKEN configurado → 401/403."""
    original = settings.API_TOKEN
    settings.API_TOKEN = "configurado"
    try:
        r = _post_cartao(client_com_auth, token=None, imagem_bytes=b"x")
        assert r.status_code in (401, 403)
    finally:
        settings.API_TOKEN = original


# ── API_TOKEN em branco (padrão) ──────────────────────────────────────────────


def test_api_token_vazio_retorna_401(client_com_auth):
    """API_TOKEN vazio → 401 mesmo com header presente."""
    original = settings.API_TOKEN
    settings.API_TOKEN = ""
    try:
        r = _post_cartao(client_com_auth, token="qualquer", imagem_bytes=b"x")
        assert r.status_code == 401
        assert "API_TOKEN não configurado" in r.json()["detail"]
    finally:
        settings.API_TOKEN = original


# ── Token errado ──────────────────────────────────────────────────────────────


def test_token_errado_retorna_401(client_com_auth):
    """Token presente mas incorreto → 401."""
    original = settings.API_TOKEN
    settings.API_TOKEN = "segredo-correto"
    try:
        r = _post_cartao(client_com_auth, token="token-errado", imagem_bytes=b"x")
        assert r.status_code == 401
        assert "Token inválido" in r.json()["detail"]
    finally:
        settings.API_TOKEN = original


# ── Token correto ─────────────────────────────────────────────────────────────


def test_token_correto_retorna_200(client_com_auth, imagem_bytes):
    """Token correto → POST /cartao retorna 200."""
    original = settings.API_TOKEN
    settings.API_TOKEN = "meu-token"
    try:
        r = _post_cartao(client_com_auth, token="meu-token", imagem_bytes=imagem_bytes)
        assert r.status_code == 200
    finally:
        settings.API_TOKEN = original
