"""
conftest.py — Fixtures globais reutilizadas em toda a suite de testes.

Estrutura de mocks:
  fake_redis          → fakeredis.FakeRedis (sem servidor real)
  fake_cache          → GridCache sobre fake_redis
  mock_extrator       → MockExtrator com Resultado OK controlado
  mock_extrator_falho → MockExtrator que sempre retorna Status.FALHOU
  mock_extrator_parcial → MockExtrator que retorna Status.PARCIAL
  mock_broker         → AsyncMock do RedisBroker (publish não faz nada)
  client              → TestClient com todas as deps sobrescritas (auth off)
  client_falho        → TestClient com extrator que sempre falha
  client_parcial      → TestClient com extrator que retorna parcial
  client_com_auth     → TestClient sem overrides de auth (testa autenticação real)

Integração (pipeline real, sem mocks de IA):
  imagem_path         → Path para imagem real (--imagem ou data/cartao_foto.jpg)
  client_real         → TestClient com ExtratorCartao real + FakeRedis
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import cv2
import fakeredis
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.deps import get_broker, get_cache, get_extrator, verify_token
from src.infrastructure.cache import GridCache
from src.models.resultado import Resultado, Status
from src.services.cartao_service import ExtratorCartao


# ── Detecção de Tesseract ─────────────────────────────────────────────────────


def _tesseract_disponivel() -> bool:
    """Verifica se o Tesseract OCR está acessível no PATH."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


TESSERACT_DISPONIVEL: bool = _tesseract_disponivel()


# ── Imagem sintética ──────────────────────────────────────────────────────────


@pytest.fixture
def imagem_branca() -> np.ndarray:
    """Imagem 200×300 px totalmente branca (BGR)."""
    return np.ones((200, 300, 3), dtype=np.uint8) * 255


@pytest.fixture
def imagem_realista() -> np.ndarray:
    """
    Imagem 1000×800 px cinza uniforme — usada como img_alinhada nos mocks.
    Tamanho próximo ao de um cartão real para não quebrar visualizer.
    """
    return np.ones((1000, 800, 3), dtype=np.uint8) * 200


@pytest.fixture
def imagem_bytes(imagem_branca: np.ndarray) -> bytes:
    """Bytes JPEG da imagem branca — usado em uploads multipart."""
    _, buf = cv2.imencode(".jpg", imagem_branca)
    return buf.tobytes()


# ── Redis / Cache fake ────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis():
    """FakeRedis em memória — sem servidor externo necessário."""
    r = fakeredis.FakeRedis()
    yield r
    r.flushall()


@pytest.fixture
def fake_cache(fake_redis) -> GridCache:
    """GridCache com backend FakeRedis."""
    return GridCache(fake_redis)


# ── Extrator mock ─────────────────────────────────────────────────────────────


class MockExtrator(ExtratorCartao):
    """
    Substituto de ExtratorCartao que devolve um Resultado fixo.
    Não toca em OpenCV, OCR nem algoritmos de detecção reais.
    """

    def __init__(self, resultado: Resultado) -> None:
        self._resultado = resultado

    def processar_bytes(self, data: bytes, dia: int = 1) -> Resultado:  # type: ignore[override]
        return self._resultado

    def processar_arquivo(self, img_path: str, dia: int = 1) -> Resultado:  # type: ignore[override]
        return self._resultado


def _make_resultado_ok(img: np.ndarray | None = None) -> Resultado:
    return Resultado(
        cpf="12345678900",
        respostas={i: "A" for i in range(1, 91)},
        status=Status.OK,
        avisos=[],
        tentativas_cpf=1,
        total_questoes_detectadas=90,
        img_alinhada=img
        if img is not None
        else np.ones((1000, 800, 3), np.uint8) * 200,
    )


def _make_resultado_parcial(img: np.ndarray | None = None) -> Resultado:
    return Resultado(
        cpf=None,
        respostas={i: "B" for i in range(1, 46)},
        status=Status.PARCIAL,
        avisos=["CPF não detectado.", "45/90 questoes detectadas."],
        tentativas_cpf=0,
        total_questoes_detectadas=45,
        img_alinhada=img
        if img is not None
        else np.ones((1000, 800, 3), np.uint8) * 200,
    )


def _make_resultado_falho() -> Resultado:
    return Resultado(
        cpf=None,
        respostas={},
        status=Status.FALHOU,
        avisos=["CPF não detectado.", "0/90 questoes detectadas."],
        tentativas_cpf=0,
        total_questoes_detectadas=0,
        img_alinhada=None,
    )


@pytest.fixture
def mock_extrator() -> MockExtrator:
    """Extrator que sempre retorna Status.OK com 90 respostas."""
    return MockExtrator(_make_resultado_ok())


@pytest.fixture
def mock_extrator_falho() -> MockExtrator:
    """Extrator que sempre retorna Status.FALHOU sem imagem alinhada."""
    return MockExtrator(_make_resultado_falho())


@pytest.fixture
def mock_extrator_parcial() -> MockExtrator:
    """Extrator que retorna Status.PARCIAL com 45 respostas e sem CPF."""
    return MockExtrator(_make_resultado_parcial())


# ── Broker mock ───────────────────────────────────────────────────────────────


@pytest.fixture
def mock_broker():
    """RedisBroker mock — publish é um AsyncMock que não faz nada."""
    broker = AsyncMock()
    broker.publish = AsyncMock(return_value=None)
    return broker


# ── Helpers para montar TestClient com overrides ──────────────────────────────


def _build_client(extrator, cache, broker) -> TestClient:
    """Constrói TestClient com auth desativada e deps substituídas."""
    app.dependency_overrides[verify_token] = lambda: None
    app.dependency_overrides[get_extrator] = lambda: extrator
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_broker] = lambda: broker
    client = TestClient(app, raise_server_exceptions=True)
    return client


# ── Fixtures de TestClient ────────────────────────────────────────────────────


@pytest.fixture
def client(fake_cache, mock_extrator, mock_broker) -> TestClient:
    """
    TestClient principal:
    - Auth desativada (verify_token → None)
    - Extrator sempre retorna Status.OK / 90 respostas
    """
    c = _build_client(mock_extrator, fake_cache, mock_broker)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_falho(fake_cache, mock_extrator_falho, mock_broker) -> TestClient:
    """TestClient com extrator que sempre falha (sem img_alinhada)."""
    c = _build_client(mock_extrator_falho, fake_cache, mock_broker)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_parcial(fake_cache, mock_extrator_parcial, mock_broker) -> TestClient:
    """TestClient com extrator retornando resultado parcial."""
    c = _build_client(mock_extrator_parcial, fake_cache, mock_broker)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_com_auth(fake_cache, mock_extrator, mock_broker) -> TestClient:
    """
    TestClient SEM override de verify_token — usado nos testes de autenticação.
    Somente get_extrator, get_cache e get_broker são sobrescritos.
    """
    app.dependency_overrides[get_extrator] = lambda: mock_extrator
    app.dependency_overrides[get_cache] = lambda: fake_cache
    app.dependency_overrides[get_broker] = lambda: mock_broker
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


# ── Integração (pipeline real) ────────────────────────────────────────────────

# Imagens padrão disponíveis em data/
_DATA_DIR = Path(__file__).parent.parent / "data"
_IMAGENS_PADRAO = [
    _DATA_DIR / "cartao_foto_tests.jpg",
    _DATA_DIR / "cartao_digitalizado_tests.jpg",
]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Adiciona --imagem para testes de integração com imagem real."""
    parser.addoption(
        "--imagem",
        action="store",
        default=None,
        metavar="PATH",
        help=(
            "Caminho para imagem real de cartão-resposta usada nos testes de "
            "integração. Se omitido, procura em data/cartao_foto_tests.jpg ou "
            "data/cartao_digitalizado_tests.jpg."
        ),
    )
    parser.addoption(
        "--dia",
        action="store",
        type=int,
        default=1,
        metavar="N",
        help="Dia da prova usado nos testes de integração (padrão: 1).",
    )
    parser.addoption(
        "--salvar-grid",
        action="store_true",
        default=False,
        help="Salva as imagens de grid geradas nos testes de integração em outputs/.",
    )


@pytest.fixture(scope="session")
def imagem_path(request: pytest.FixtureRequest) -> Path:
    """
    Resolve o caminho da imagem real para testes de integração.

    Ordem de busca:
    1. Argumento --imagem passado na linha de comando.
    2. Primeiro arquivo existente em data/ (cartao_foto.jpg, cartao_digitalizado.jpg).

    O teste que usar esta fixture é automaticamente pulado se nenhuma imagem
    for encontrada.
    """
    cli_path = request.config.getoption("--imagem")
    if cli_path:
        p = Path(cli_path)
        if not p.exists():
            pytest.skip(f"Imagem não encontrada: {p}")
        return p

    for candidate in _IMAGENS_PADRAO:
        if candidate.exists():
            return candidate

    pytest.skip(
        "Nenhuma imagem real disponível. "
        "Forneça --imagem <path> ou adicione uma imagem em data/."
    )


@pytest.fixture(scope="session")
def dia_prova(request: pytest.FixtureRequest) -> int:
    """Dia da prova lido do argumento --dia (padrão: 1)."""
    return int(request.config.getoption("--dia"))


@pytest.fixture(scope="session")
def tesseract_disponivel() -> bool:
    """Indica se o Tesseract OCR está disponível no ambiente."""
    return TESSERACT_DISPONIVEL


@pytest.fixture(scope="session")
def client_real(tmp_path_factory) -> TestClient:  # type: ignore[return]
    """
    TestClient com pipeline REAL:
    - ExtratorCartao verdadeiro (OpenCV + HoughCircles + detecção de bolhas)
    - GridCache sobre FakeRedis (sem servidor Redis externo)
    - RedisBroker mockado (publish não dispara stream real)
    - Auth desativada

    OCR (Tesseract): se não estiver instalado, pytesseract.image_to_string é
    mockado para retornar string vazia — CPF não será detectado, mas o pipeline
    completo de detecção de bolhas é executado normalmente.

    Escopo session: uma única instância compartilhada entre todos os testes
    de integração para evitar re-criar o app desnecessariamente.
    """
    from src.services.cartao_service import ExtratorCartao

    real_redis = fakeredis.FakeRedis()
    real_cache = GridCache(real_redis)
    real_extrator = ExtratorCartao()
    broker_mock = AsyncMock()
    broker_mock.publish = AsyncMock(return_value=None)

    app.dependency_overrides[verify_token] = lambda: None
    app.dependency_overrides[get_extrator] = lambda: real_extrator
    app.dependency_overrides[get_cache] = lambda: real_cache
    app.dependency_overrides[get_broker] = lambda: broker_mock

    tess_patch = None
    if not TESSERACT_DISPONIVEL:
        tess_patch = patch(
            "src.core.ocr.pytesseract.image_to_string",
            return_value="",
        )
        tess_patch.start()

    c = TestClient(app, raise_server_exceptions=True)
    yield c

    if tess_patch is not None:
        tess_patch.stop()
    app.dependency_overrides.clear()
    real_redis.flushall()
