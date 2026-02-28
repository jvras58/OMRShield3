"""
Lógica de negócio das rotas da API OMR.

As funções recebem extrator e cache como parâmetros explícitos
(injetados pelo FastAPI via Depends).
"""

import logging
import uuid

from fastapi import HTTPException

from src.api.cartao.schemas import BatchItemResponse, BatchResponse, CartaoResponse
from src.core.visualizer import render_para_b64, render_para_bytes
from src.infrastructure.cache import GridCache
from src.services.cartao_service import ExtratorCartao
from src.settings.config import settings

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
        cache.set(job_id, resultado.img_alinhada, resultado.respostas, dia)
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


def processar_lote(
    arquivos: list[tuple[str, bytes]],
    dia: int,
    extrator: ExtratorCartao,
    cache: GridCache,
) -> BatchResponse:
    """Processa uma lista de (nome, bytes) e devolve o BatchResponse."""
    resultados = []

    for nome, data in arquivos:
        try:
            r = processar_upload(
                data, dia=dia, incluir_grid=False, extrator=extrator, cache=cache
            )
            resultados.append(
                BatchItemResponse(
                    arquivo=nome,
                    job_id=r.job_id,
                    status=r.status,
                    cpf=r.cpf,
                    total_questoes_detectadas=r.total_questoes_detectadas,
                    respostas=r.respostas,
                    avisos=r.avisos,
                    grid_url=r.grid_url,
                )
            )
        except Exception as exc:
            log.exception("Erro ao processar arquivo '%s'", nome)
            resultados.append(
                BatchItemResponse(
                    arquivo=nome,
                    job_id=None,
                    status="falhou",
                    cpf=None,
                    total_questoes_detectadas=0,
                    respostas={},
                    avisos=[str(exc)],
                )
            )

    return BatchResponse(
        total_arquivos=len(resultados),
        processados=sum(1 for r in resultados if r.status != "falhou"),
        resultados=resultados,
    )


def obter_grid_jpeg(job_id: str, cache: GridCache) -> bytes:
    """Recupera e renderiza o grid JPEG de um job_id. Levanta 404 se não encontrado."""
    entry = cache.get(job_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_id '{job_id}' não encontrado ou expirado "
            f"(TTL: {settings.CACHE_TTL_SECONDS}s).",
        )

    img, respostas, dia = entry
    return render_para_bytes(img, respostas, dia)
