"""
api/routes.py — Handlers das rotas FastAPI do OMR.

Monta o router que é registrado em api/app.py.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import conint

from src.api.schemas import BatchItemResponse, BatchResponse, CartaoResponse
from src.core.visualizer import render_para_b64, render_para_bytes
from src.infrastructure.cache import grid_cache
from src.services.cartao_service import ExtratorCartao
from src.settings.config import settings

log = logging.getLogger(__name__)
router = APIRouter()
_extrator = ExtratorCartao()


# ── Helper ────────────────────────────────────────────────────────────────────


def _processar_upload(data: bytes, dia: int, incluir_grid: bool) -> CartaoResponse:
    job_id = str(uuid.uuid4())
    resultado = _extrator.processar_bytes(data, dia=dia)

    grid_b64 = None
    grid_url = None

    if resultado.img_alinhada is not None:
        grid_cache.set(job_id, resultado.img_alinhada, resultado.respostas, dia)
        grid_url = f"/cartao/{job_id}/grid"

        if incluir_grid:
            grid_b64 = render_para_b64(resultado.img_alinhada, resultado.respostas, dia)

    return CartaoResponse(
        job_id=job_id,
        status=resultado.status.value,
        cpf=resultado.cpf,
        tentativas_cpf=resultado.tentativas_cpf,
        total_questoes_detectadas=resultado.total_questoes_detectadas,
        questoes_esperadas=settings.QUESTOES_POR_DIA,
        respostas=resultado.respostas,
        avisos=resultado.avisos,
        grid_image_b64=grid_b64,
        grid_url=grid_url,
    )


# ── Rotas ─────────────────────────────────────────────────────────────────────


@router.post("/cartao", response_model=CartaoResponse, summary="Processar cartão")
async def processar_cartao(
    file: Annotated[UploadFile, File(description="Imagem JPEG/PNG do cartão-resposta")],
    dia: Annotated[conint(ge=1), Form(description="Dia da prova (1, 2, ...)")] = 1,
    incluir_grid: Annotated[
        bool,
        Form(
            description="Se true, retorna imagem do grid em base64 no campo grid_image_b64"
        ),
    ] = False,
):
    """
    Processa uma imagem do cartão-resposta e retorna:
    - JSON com respostas detectadas (Q1–Q90)
    - CPF (se detectável via OCR)
    - Imagem do grid anotado (base64, se incluir_grid=true)
    - URL para baixar a imagem do grid posteriormente
    """
    data = await file.read()
    try:
        return _processar_upload(data, dia=dia, incluir_grid=incluir_grid)
    except Exception as exc:
        log.exception("Erro ao processar cartão")
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/cartao/batch",
    response_model=BatchResponse,
    summary="Processar múltiplos cartões",
)
async def processar_lote(
    files: list[UploadFile] = File(description="Lista de imagens"),
    dia: Annotated[conint(ge=1), Form(description="Dia da prova")] = 1,
):
    """
    Processa múltiplas imagens em sequência.
    Cada resultado inclui `grid_url` para visualização posterior.
    """
    resultados = []
    for file in files:
        data = await file.read()
        try:
            r = _processar_upload(data, dia=dia, incluir_grid=False)
            resultados.append(
                BatchItemResponse(
                    arquivo=file.filename or "?",
                    job_id=r.job_id,
                    status=r.status,
                    cpf=r.cpf,
                    total_questoes_detectadas=r.total_questoes_detectadas,
                    respostas=r.respostas,
                    avisos=r.avisos,
                    grid_url=r.grid_url,
                )
            )
        except Exception as e:
            log.exception(f"Erro em {file.filename}")
            resultados.append(
                BatchItemResponse(
                    arquivo=file.filename or "?",
                    job_id=None,
                    status="falhou",
                    cpf=None,
                    total_questoes_detectadas=0,
                    respostas={},
                    avisos=[str(e)],
                )
            )

    return BatchResponse(
        total_arquivos=len(files),
        processados=sum(1 for r in resultados if r.status != "falhou"),
        resultados=resultados,
    )


@router.get(
    "/cartao/{job_id}/grid",
    response_class=Response,
    summary="Baixar imagem do grid",
    responses={200: {"content": {"image/jpeg": {}}}, 404: {}},
)
async def grid_imagem(job_id: str):
    """
    Retorna a imagem JPEG do grid anotado de um processamento anterior.
    O `job_id` é retornado na resposta do POST /cartao.
    """
    entry = grid_cache.get(job_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail="job_id não encontrado ou expirado."
        )

    img, respostas, dia = entry
    jpeg = render_para_bytes(img, respostas, dia)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}
