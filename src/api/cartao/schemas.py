"""
api/cartao/schemas.py — Schemas Pydantic para request/response da API.
"""

from typing import Optional

from pydantic import BaseModel


class CartaoResponse(BaseModel):
    job_id: str
    status: str
    cpf: Optional[str]
    tentativas_cpf: int
    total_questoes_detectadas: int
    questoes_esperadas: int
    respostas: dict[int, str]
    avisos: list[str]
    grid_image_b64: Optional[str] = None
    grid_url: Optional[str] = None


class BatchItemResponse(BaseModel):
    arquivo: str
    job_id: Optional[str]
    status: str
    cpf: Optional[str]
    total_questoes_detectadas: int
    respostas: dict[int, str]
    avisos: list[str]
    grid_url: Optional[str] = None


class BatchResponse(BaseModel):
    total_arquivos: int
    processados: int
    resultados: list[BatchItemResponse]

class BatchEnqueueResponse(BaseModel):
    """Resposta imediata do POST /cartao/batch — retorna antes do processamento."""

    job_ids: list[str]
    total: int
    status: str = "enqueued"
    status_url_tpl: str


class JobStatusResponse(BaseModel):
    """Resposta do GET /cartao/{job_id}/status."""

    job_id: str
    status: str
    respostas: Optional[dict[int, str]] = None
    cpf: Optional[str] = None
    avisos: Optional[list[str]] = None
    grid_url: Optional[str] = None
