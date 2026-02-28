"""
app.py — API FastAPI para o OMR sem template.

Endpoints:
  POST /cartao        → processa e retorna JSON + grid visual (base64)
  POST /cartao/batch  → processa múltiplas imagens
  GET  /cartao/{id}/grid → retorna imagem do grid como arquivo (image/jpeg)
  GET  /health
"""

import base64
import logging
import uuid
from typing import Annotated, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, conint

from src.extractor import ExtratorCartao, Status, QUESTOES_POR_DIA
from src.visualizer import render_para_bytes, render_para_b64

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

app      = FastAPI(
    title="OMR AutoDetect",
    description=(
        "Leitura de cartões-resposta SIMUREKA por auto-detecção de bolhas.\n\n"
        "Funciona com foto de celular e scanner — sem necessidade de template."
    ),
    version="1.0.0",
)
_extrator = ExtratorCartao()

# Cache em memória para o endpoint /cartao/{id}/grid
# Estrutura: {job_id: (img_alinhada, respostas, dia)}
_cache: dict[str, tuple] = {}
_CACHE_MAX = 100


# ── Schemas ───────────────────────────────────────────────────────────────────

class CartaoResponse(BaseModel):
    job_id:                    str
    status:                    str
    cpf:                       Optional[str]
    tentativas_cpf:            int
    total_questoes_detectadas: int
    questoes_esperadas:        int
    respostas:                 dict[int, str]
    avisos:                    list[str]
    # Imagem do grid em base64 (JPEG). Presente se incluir_grid=true.
    grid_image_b64:            Optional[str] = None
    # URL para buscar a imagem depois (sempre presente)
    grid_url:                  Optional[str] = None


class BatchItemResponse(BaseModel):
    arquivo:                   str
    job_id:                    Optional[str]
    status:                    str
    cpf:                       Optional[str]
    total_questoes_detectadas: int
    respostas:                 dict[int, str]
    avisos:                    list[str]
    grid_url:                  Optional[str] = None


class BatchResponse(BaseModel):
    total_arquivos: int
    processados:    int
    resultados:     list[BatchItemResponse]


# ── Helper ────────────────────────────────────────────────────────────────────

def _guardar_cache(job_id: str, img: np.ndarray, respostas: dict, dia: int):
    """Mantém o cache com limite de tamanho (remove o mais antigo)."""
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[job_id] = (img, respostas, dia)


def _processar_upload(data: bytes, dia: int, incluir_grid: bool) -> CartaoResponse:
    job_id    = str(uuid.uuid4())
    resultado = _extrator.processar_bytes(data, dia=dia)

    grid_b64 = None
    grid_url = None

    if resultado.img_alinhada is not None:
        _guardar_cache(job_id, resultado.img_alinhada, resultado.respostas, dia)
        grid_url = f"/cartao/{job_id}/grid"

        if incluir_grid:
            grid_b64 = render_para_b64(
                resultado.img_alinhada, resultado.respostas, dia
            )

    return CartaoResponse(
        job_id                    = job_id,
        status                    = resultado.status.value,
        cpf                       = resultado.cpf,
        tentativas_cpf            = resultado.tentativas_cpf,
        total_questoes_detectadas = resultado.total_questoes_detectadas,
        questoes_esperadas        = QUESTOES_POR_DIA,
        respostas                 = resultado.respostas,
        avisos                    = resultado.avisos,
        grid_image_b64            = grid_b64,
        grid_url                  = grid_url,
    )


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.post("/cartao", response_model=CartaoResponse, summary="Processar cartão")
async def processar_cartao(
    file: Annotated[UploadFile, File(description="Imagem JPEG/PNG do cartão-resposta")],
    dia:  Annotated[conint(ge=1), Form(description="Dia da prova (1, 2, ...)")] = 1,
    incluir_grid: Annotated[bool, Form(
        description="Se true, retorna imagem do grid em base64 no campo grid_image_b64"
    )] = False,
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
        logging.exception("Erro ao processar cartão")
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/cartao/batch",
    response_model=BatchResponse,
    summary="Processar múltiplos cartões",
)
async def processar_lote(
    files: list[UploadFile] = File(description="Lista de imagens"),
    dia:   Annotated[conint(ge=1), Form(description="Dia da prova")] = 1,
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
            resultados.append(BatchItemResponse(
                arquivo                   = file.filename or "?",
                job_id                    = r.job_id,
                status                    = r.status,
                cpf                       = r.cpf,
                total_questoes_detectadas = r.total_questoes_detectadas,
                respostas                 = r.respostas,
                avisos                    = r.avisos,
                grid_url                  = r.grid_url,
            ))
        except Exception as e:
            logging.exception(f"Erro em {file.filename}")
            resultados.append(BatchItemResponse(
                arquivo                   = file.filename or "?",
                job_id                    = None,
                status                    = "falhou",
                cpf                       = None,
                total_questoes_detectadas = 0,
                respostas                 = {},
                avisos                    = [str(e)],
            ))

    return BatchResponse(
        total_arquivos = len(files),
        processados    = sum(1 for r in resultados if r.status != "falhou"),
        resultados     = resultados,
    )


@app.get(
    "/cartao/{job_id}/grid",
    response_class=Response,
    summary="Baixar imagem do grid",
    responses={200: {"content": {"image/jpeg": {}}}, 404: {}},
)
async def grid_imagem(job_id: str):
    """
    Retorna a imagem JPEG do grid anotado de um processamento anterior.
    O job_id vem do campo `job_id` da resposta do POST /cartao.
    """
    if job_id not in _cache:
        raise HTTPException(status_code=404, detail="job_id não encontrado ou expirado.")

    img, respostas, dia = _cache[job_id]
    try:
        jpeg = render_para_bytes(img, respostas, dia, fmt="jpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/health", summary="Health check")
def health():
    return {
        "status":  "ok",
        "modelo":  "auto-detect (sem template)",
        "versao":  "1.0.0",
    }
