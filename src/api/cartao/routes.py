"""
api/cartao/routes.py — Definição das rotas FastAPI do OMR.

Apenas o contrato HTTP (path, método, schema).
Toda a lógica vive em controllers.py.
Dependências (extrator, cache, broker) são injetadas via Depends().
"""

import logging
from typing import Annotated
import asyncio
from functools import partial
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import conint

from src.api.cartao.controllers import (
    consultar_status,
    enfileirar_lote,
    obter_grid_jpeg,
    processar_upload,
)
from src.api.cartao.schemas import (
    BatchEnqueueResponse,
    CartaoResponse,
    JobStatusResponse,
)
from src.api.deps import BrokerDep, CacheDep, ExtractorDep, verify_token

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_token)])


@router.post("/cartao", response_model=CartaoResponse, summary="Processar cartão")
async def processar_cartao(
    file: Annotated[UploadFile, File(description="Imagem JPEG/PNG do cartão-resposta")],
    extrator: ExtractorDep,
    cache: CacheDep,
    dia: Annotated[conint(ge=1), Form(description="Dia da prova (1, 2, ...)")] = 1,
    incluir_grid: Annotated[
        bool, Form(description="Se true, retorna grid_image_b64 no JSON")
    ] = False,
):
    """
    Processa uma imagem do cartão-resposta **de forma síncrona** e retorna:
    - JSON com respostas detectadas (Q1–Q90)
    - CPF (se detectável via OCR)
    - Imagem do grid anotado em base64 (se incluir_grid=true)
    - URL para baixar a imagem do grid posteriormente

    Para múltiplos cartões sem bloquear a API, use `POST /cartao/batch`.
    """
    data = await file.read()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(
            processar_upload,
            data,
            dia=dia,
            incluir_grid=incluir_grid,
            extrator=extrator,
            cache=cache,
        ),
    )


@router.post(
    "/cartao/batch",
    response_model=BatchEnqueueResponse,
    summary="Enfileirar múltiplos cartões",
)
async def processar_lote_route(
    cache: CacheDep,
    broker: BrokerDep,
    files: Annotated[list[UploadFile], File(description="Lista de imagens")],
    dia: Annotated[conint(ge=1), Form(description="Dia da prova")] = 1,
):
    """
    Enfileira múltiplas imagens no Redis Stream `omr.batch` para processamento
    assíncrono pelos workers — **retorna imediatamente** com os job_ids.

    Acompanhe o progresso com `GET /cartao/{job_id}/status`.
    Após concluído, baixe o grid com `GET /cartao/{job_id}/grid`.
    """
    arquivos = [(f.filename or "?", await f.read()) for f in files]
    return await enfileirar_lote(arquivos, dia=dia, cache=cache, broker=broker)


@router.get(
    "/cartao/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Consultar status do job",
)
async def job_status(job_id: str, cache: CacheDep):
    """
    Retorna o status de processamento de um job enfileirado via batch.

    - `pending` — worker ainda não processou
    - `done`    — processado com sucesso; respostas disponíveis
    - `failed`  — erro irrecuperável; ver campo `avisos`
    """
    return consultar_status(job_id, cache=cache)


@router.get(
    "/cartao/{job_id}/grid",
    response_class=Response,
    summary="Baixar imagem do grid",
    responses={200: {"content": {"image/jpeg": {}}}, 404: {}},
)
async def grid_imagem(job_id: str, cache: CacheDep):
    """
    Retorna a imagem JPEG do grid anotado.
    Disponível após `status == done`.
    Expira após CACHE_TTL_SECONDS segundos (padrão: 1 hora).
    """
    jpeg = obter_grid_jpeg(job_id, cache=cache)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}
