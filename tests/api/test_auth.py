"""
tests/api/test_auth.py — Testa o mecanismo de autenticação via X-Verify-Token.

A aplicação usa APIKeyHeader para ler o header.
O comportamento esperado:
  - Sem header           → 403 (FastAPI rejeita antes de chamar verify_token)
  - API_TOKEN vazio      → 401 (verify_token levanta HTTPException)
  - Token errado         → 401
  - Token correto        → 200
"""

from src.settings.config import settings


# ── Sem token algum ───────────────────────────────────────────────────────────


def test_sem_token_api_token_vazio_retorna_401(client_com_auth):
    """
    Quando o header X-Verify-Token está ausente E API_TOKEN não está configurado
    (string vazia), verify_token levanta HTTP 401.
    """
    original = settings.API_TOKEN
    settings.API_TOKEN = ""
    try:
        r = client_com_auth.get("/health")
        assert r.status_code == 401
    finally:
        settings.API_TOKEN = original


def test_sem_token_com_api_token_configurado_retorna_4xx(client_com_auth):
    """
    Quando o header está ausente e API_TOKEN está configurado,
    a API recusa a requisição (401 ou 403).
    """
    original = settings.API_TOKEN
    settings.API_TOKEN = "configurado"
    try:
        r = client_com_auth.get("/health")  # sem header X-Verify-Token
        assert r.status_code in (401, 403)
    finally:
        settings.API_TOKEN = original


# ── API_TOKEN em branco (padrão) ──────────────────────────────────────────────


def test_api_token_vazio_retorna_401(client_com_auth):
    """
    Quando API_TOKEN não está configurado (string vazia),
    verify_token levanta 401 independente do valor enviado.
    """
    original = settings.API_TOKEN
    settings.API_TOKEN = ""
    try:
        r = client_com_auth.get("/health", headers={"X-Verify-Token": "qualquer"})
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
        r = client_com_auth.get("/health", headers={"X-Verify-Token": "token-errado"})
        assert r.status_code == 401
        assert "Token inválido" in r.json()["detail"]
    finally:
        settings.API_TOKEN = original


# ── Token correto ─────────────────────────────────────────────────────────────


def test_token_correto_retorna_200(client_com_auth):
    """Token correto → health check retorna 200."""
    original = settings.API_TOKEN
    settings.API_TOKEN = "meu-token"
    try:
        r = client_com_auth.get("/health", headers={"X-Verify-Token": "meu-token"})
        assert r.status_code == 200
    finally:
        settings.API_TOKEN = original


def test_token_correto_post_cartao(client_com_auth, imagem_bytes):
    """Token correto em POST /cartao → 200."""
    original = settings.API_TOKEN
    settings.API_TOKEN = "meu-token"
    try:
        r = client_com_auth.post(
            "/cartao",
            headers={"X-Verify-Token": "meu-token"},
            data={"dia": "1"},
            files={"file": ("cartao.jpg", imagem_bytes, "image/jpeg")},
        )
        assert r.status_code == 200
    finally:
        settings.API_TOKEN = original
