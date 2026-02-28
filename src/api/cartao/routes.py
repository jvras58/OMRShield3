"""
api/routes.py — Definição das rotas FastAPI do OMR.

Apenas o contrato HTTP (path, método, schema).
Toda a lógica vive em api/controllers.py.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import conint

from src.api.cartao.controllers import obter_grid_jpeg, processar_lote, processar_upload
from src.api.cartao.schemas import BatchResponse, CartaoResponse

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/cartao", response_model=CartaoResponse, summary="Processar cartão")
async def processar_cartao(
    file: Annotated[UploadFile, File(description="Imagem JPEG/PNG do cartão-resposta")],
    dia: Annotated[conint(ge=1), Form(description="Dia da prova (1, 2, ...)")] = 1,
    incluir_grid: Annotated[
        bool,
        Form(description="Se true, retorna grid_image_b64 no JSON de resposta"),
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
        return processar_upload(data, dia=dia, incluir_grid=incluir_grid)
    except Exception as exc:
        log.exception("Erro ao processar cartão")
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/cartao/batch",
    response_model=BatchResponse,
    summary="Processar múltiplos cartões",
)
async def processar_lote_route(
    files: list[UploadFile] = File(description="Lista de imagens"),
    dia: Annotated[conint(ge=1), Form(description="Dia da prova")] = 1,
):
    """
    Processa múltiplas imagens em sequência.
    Cada resultado inclui `grid_url` para visualização posterior.
    """
    arquivos = [(f.filename or "?", await f.read()) for f in files]
    return processar_lote(arquivos, dia=dia)


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
    jpeg = obter_grid_jpeg(job_id)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}
