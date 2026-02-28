"""
api/cartao/controllers.py — Lógica de negócio das rotas da API OMR.

As funções recebem extrator, cache e broker como parâmetros explícitos
(injetados pelo FastAPI via Depends) — sem globais, fácil de testar.
"""

import logging
import uuid

from fastapi import HTTPException
from faststream.redis import RedisBroker

from src.api.cartao.schemas import (
    BatchEnqueueResponse,
    CartaoResponse,
    JobStatusResponse,
)
from src.core.visualizer import render_para_b64, render_para_bytes
from src.infrastructure.cache import GridCache
from src.models.resultado import CartaoJob
from src.services.cartao_service import ExtratorCartao
from src.settings.config import settings

STREAM_NAME = "omr.batch"

log = logging.getLogger(__name__)


def processar_upload(
    data: bytes,
    dia: int,
    incluir_grid: bool,
    extrator: ExtratorCartao,
    cache: GridCache,
) -> CartaoResponse:
    """Processa bytes de uma imagem e devolve o CartaoResponse completo."""
    job_id = str(uuid.uuid4())
    resultado = extrator.processar_bytes(data, dia=dia)

    grid_b64 = None
    grid_url = None

    if resultado.img_alinhada is not None:
        cache.set(
            job_id,
            resultado.img_alinhada,
            resultado.respostas,
            dia,
            cpf=resultado.cpf,
            avisos=resultado.avisos,
        )
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


async def enfileirar_lote(
    arquivos: list[tuple[str, bytes]],
    dia: int,
    cache: GridCache,
    broker: RedisBroker,
) -> BatchEnqueueResponse:
    """
    Para cada arquivo:
      1. Salva a imagem raw no Redis (temp:{job_id})
      2. Publica mensagem leve no Redis Stream 'omr.batch'

    Retorna imediatamente com os job_ids — sem bloquear o event loop.
    """
    job_ids = []

    for filename, data in arquivos:
        job_id = str(uuid.uuid4())
        job = CartaoJob(job_id=job_id, dia=dia, filename=filename)

        cache.set_temp(job_id, data)

        await broker.publish(job.model_dump(), stream=STREAM_NAME)

        job_ids.append(job_id)
        log.info(f"[Batch] Enfileirado job_id={job_id} arquivo={filename}")

    return BatchEnqueueResponse(
        job_ids=job_ids,
        total=len(job_ids),
        status="enqueued",
        status_url_tpl="/cartao/{job_id}/status",
    )


def consultar_status(job_id: str, cache: GridCache) -> JobStatusResponse:
    """
    Consulta o Redis para saber se o job foi processado.

    Estados possíveis:
      "pending" — worker ainda não processou (temp:{job_id} existe mas meta não)
      "done"    — processado com sucesso
      "failed"  — worker encontrou erro irrecuperável
      404       — job_id desconhecido ou TTL expirado
    """
    status_data = cache.get_status(job_id)

    if status_data is None:
        if cache.get_temp(job_id) is not None:
            return JobStatusResponse(job_id=job_id, status="pending")
        raise HTTPException(
            status_code=404,
            detail=f"job_id '{job_id}' não encontrado ou expirado.",
        )

    grid_url = f"/cartao/{job_id}/grid" if status_data["status"] == "done" else None

    return JobStatusResponse(
        job_id=job_id,
        status=status_data["status"],
        respostas=status_data.get("respostas"),
        cpf=status_data.get("cpf"),
        avisos=status_data.get("avisos"),
        grid_url=grid_url,
    )


def obter_grid_jpeg(job_id: str, cache: GridCache) -> bytes:
    """Recupera e renderiza o grid JPEG. Levanta 404 se não encontrado."""
    entry = cache.get(job_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_id '{job_id}' não encontrado ou expirado "
            f"(TTL: {settings.CACHE_TTL_SECONDS}s).",
        )
    img, respostas, dia = entry
    return render_para_bytes(img, respostas, dia)
