"""
tests/integration/test_smoke.py — Testes de integração com imagem real.

Equivalente pytest do scripts/smoke_test.py.

Executa o pipeline COMPLETO sem mocks de extração:
  ExtratorCartao real → OpenCV → HoughCircles → OCR → Resultado

Pré-requisito:
  Uma imagem JPEG/PNG do cartão-resposta SIMUREKA deve existir em data/ ou ser
  passada via --imagem <path>.

Como rodar apenas os testes de integração:
    uv run pytest tests/integration/ -v
    uv run pytest tests/integration/ -v --imagem data/cartao_foto.jpg --dia 1
    uv run pytest tests/integration/ -v --imagem data/cartao_foto.jpg --salvar-grid

Rodar toda a suite ignorando integração:
    uv run pytest tests/ --ignore=tests/integration/

Marcador pytest: @pytest.mark.integration
  Pulados automaticamente se nenhuma imagem real for encontrada.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# ── Fixtures locais ───────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def imagem_bytes_real(imagem_path: Path) -> bytes:
    """Lê os bytes da imagem de cartão real uma única vez por sessão."""
    return imagem_path.read_bytes()


@pytest.fixture(scope="session")
def resultado_cartao(client_real, imagem_bytes_real, imagem_path, dia_prova):
    """
    Executa POST /cartao uma única vez e compartilha o resultado na sessão.
    Evita re-processar a mesma imagem a cada teste.
    """
    r = client_real.post(
        "/cartao",
        data={"dia": str(dia_prova), "incluir_grid": "true"},
        files={"file": (imagem_path.name, imagem_bytes_real, "image/jpeg")},
    )
    assert r.status_code == 200, f"POST /cartao falhou: {r.text[:400]}"
    return r.json()


# ── health ────────────────────────────────────────────────────────────────────


def test_integration_health(client_real):
    """Pipeline real: GET /health deve retornar ok."""
    r = client_real.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── POST /cartao ──────────────────────────────────────────────────────────────


def test_integration_cartao_status_200(
    client_real, imagem_bytes_real, imagem_path, dia_prova
):
    r = client_real.post(
        "/cartao",
        data={"dia": str(dia_prova)},
        files={"file": (imagem_path.name, imagem_bytes_real, "image/jpeg")},
    )
    assert r.status_code == 200


def test_integration_cartao_nao_falhou(resultado_cartao):
    """Com imagem real, o pipeline não deve retornar 'falhou'."""
    assert resultado_cartao["status"] in ("ok", "parcial"), (
        f"Pipeline retornou 'falhou'. Avisos: {resultado_cartao['avisos']}"
    )


def test_integration_cartao_detectou_questoes(resultado_cartao):
    """Deve detectar pelo menos 1 questão em uma imagem real."""
    n = resultado_cartao["total_questoes_detectadas"]
    assert n > 0, f"Nenhuma questão detectada. Avisos: {resultado_cartao['avisos']}"


def test_integration_cartao_respostas_sao_letras_validas(resultado_cartao):
    """Todas as respostas detectadas devem ser A, B, C, D ou E."""
    for q, letra in resultado_cartao["respostas"].items():
        assert letra in ("A", "B", "C", "D", "E"), (
            f"Questão {q} tem resposta inválida: '{letra}'"
        )


def test_integration_cartao_tem_job_id(resultado_cartao):
    job_id = resultado_cartao["job_id"]
    assert job_id and len(job_id) > 0


def test_integration_cartao_tem_grid_url(resultado_cartao):
    """Com imagem real, img_alinhada sempre existe → grid_url não deve ser None."""
    assert resultado_cartao["grid_url"] is not None, (
        "grid_url é None — img_alinhada não foi gerada."
    )


def test_integration_cartao_grid_b64_valido(resultado_cartao):
    """incluir_grid=true deve retornar base64 decodificável."""
    b64 = resultado_cartao.get("grid_image_b64")
    assert b64 is not None, "grid_image_b64 ausente mesmo com incluir_grid=true"
    decoded = base64.b64decode(b64)
    # assinatura JPEG
    assert decoded[:3] == b"\xff\xd8\xff", "grid_image_b64 não é um JPEG válido"


def test_integration_cartao_questoes_esperadas(resultado_cartao):
    """questoes_esperadas deve bater com a configuração (N_BLOCOS × N_QUESTOES_POR_BLOCO)."""
    from src.settings.config import settings

    assert resultado_cartao["questoes_esperadas"] == settings.QUESTOES_POR_DIA


def test_integration_cartao_avisos_sao_strings(resultado_cartao):
    for av in resultado_cartao["avisos"]:
        assert isinstance(av, str)


# ── GET /cartao/{job_id}/grid ─────────────────────────────────────────────────


def test_integration_grid_retorna_jpeg(client_real, resultado_cartao):
    """Após POST /cartao, GET /grid deve devolver imagem JPEG válida."""
    job_id = resultado_cartao["job_id"]
    r = client_real.get(f"/cartao/{job_id}/grid")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff"


def test_integration_grid_tamanho_razoavel(client_real, resultado_cartao):
    """A imagem do grid deve ter pelo menos 10 KB."""
    job_id = resultado_cartao["job_id"]
    r = client_real.get(f"/cartao/{job_id}/grid")
    assert len(r.content) > 10 * 1024, f"Grid muito pequeno: {len(r.content)} bytes"


def test_integration_grid_salvar(client_real, resultado_cartao, request):
    """Salva o grid em outputs/ se --salvar-grid foi passado."""
    if not request.config.getoption("--salvar-grid", default=False):
        pytest.skip("Passe --salvar-grid para salvar o grid em outputs/")

    job_id = resultado_cartao["job_id"]
    r = client_real.get(f"/cartao/{job_id}/grid")
    assert r.status_code == 200

    out = Path("outputs") / "grid_integration.jpg"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(r.content)
    print(f"\n  Grid salvo em: {out}  ({len(r.content) // 1024} KB)")


# ── POST /cartao/batch ────────────────────────────────────────────────────────


def test_integration_batch_retorna_200(
    client_real, imagem_bytes_real, imagem_path, dia_prova
):
    r = client_real.post(
        "/cartao/batch",
        data={"dia": str(dia_prova)},
        files=[
            ("files", (imagem_path.name, imagem_bytes_real, "image/jpeg")),
            ("files", (imagem_path.name + "_copia", imagem_bytes_real, "image/jpeg")),
        ],
    )
    assert r.status_code == 200


def test_integration_batch_2_job_ids(
    client_real, imagem_bytes_real, imagem_path, dia_prova
):
    r = client_real.post(
        "/cartao/batch",
        data={"dia": str(dia_prova)},
        files=[
            ("files", (imagem_path.name, imagem_bytes_real, "image/jpeg")),
            ("files", (imagem_path.name + "_copia", imagem_bytes_real, "image/jpeg")),
        ],
    )
    data = r.json()
    assert data["total"] == 2
    assert len(data["job_ids"]) == 2
    assert data["job_ids"][0] != data["job_ids"][1]


def test_integration_batch_status_enqueued(
    client_real, imagem_bytes_real, imagem_path, dia_prova
):
    r = client_real.post(
        "/cartao/batch",
        data={"dia": str(dia_prova)},
        files=[("files", (imagem_path.name, imagem_bytes_real, "image/jpeg"))],
    )
    assert r.json()["status"] == "enqueued"


# ── Resumo diagnóstico ────────────────────────────────────────────────────────


def test_integration_imprimir_resumo(
    resultado_cartao, imagem_path, dia_prova, tesseract_disponivel, capsys
):
    """
    Imprime um resumo legivel do resultado -- equivalente ao output do smoke_test.
    Sempre passa; serve como saida de diagnostico ao rodar com -v -s.
    """
    d = resultado_cartao
    n = d["total_questoes_detectadas"]
    exp = d["questoes_esperadas"]
    status = d["status"]
    cpf = d["cpf"]
    avisos = d["avisos"]
    respostas = d["respostas"]

    ocr_info = (
        "Tesseract real"
        if tesseract_disponivel
        else "OCR mockado (Tesseract nao instalado)"
    )

    with capsys.disabled():
        print(f"\n{'=' * 60}")
        print(f"  INTEGRACAO -- {imagem_path.name}  (dia={dia_prova})")
        print(f"  OCR: {ocr_info}")
        print(f"{'=' * 60}")
        print(f"  status={status}  cpf={cpf}  questoes={n}/{exp}  avisos={len(avisos)}")
        if avisos:
            for av in avisos:
                print(f"     [!] {av}")
        print("\n  Respostas detectadas:")
        linha = "  "
        for i, (q, r_) in enumerate(
            sorted((int(k), v) for k, v in respostas.items()), 1
        ):
            linha += f"Q{q:02d}:{r_:<2} "
            if i % 15 == 0:
                print(linha)
                linha = "  "
        if linha.strip():
            print(linha)
        print(f"{'=' * 60}")
