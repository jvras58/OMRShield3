"""
tests/api/test_health.py — Testa o endpoint GET /health.
"""


def test_health_retorna_status_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_content_type_json(client):
    r = client.get("/health")
    assert "application/json" in r.headers["content-type"]
