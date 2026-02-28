"""
models/resultado.py — Modelos de domínio do pipeline de extração.

Resultado     — saída do ExtratorCartao (uso interno, não serializado)
CartaoJob     — mensagem publicada na fila Redis Stream (serializada como JSON)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
from pydantic import BaseModel


class Status(Enum):
    OK = "ok"
    PARCIAL = "parcial"
    FALHOU = "falhou"


@dataclass
class Resultado:
    cpf: Optional[str] = None
    respostas: dict = field(default_factory=dict)
    status: Status = Status.FALHOU
    avisos: list = field(default_factory=list)
    tentativas_cpf: int = 0
    total_questoes_detectadas: int = 0
    img_alinhada: Optional[np.ndarray] = field(default=None, repr=False)


class CartaoJob(BaseModel):
    """
    Mensagem publicada no Redis Stream 'omr.batch' para cada cartão enfileirado.

    A imagem é armazenada no Redis em chave separada (temp:{job_id})
    para não estourar o limite de tamanho de mensagem do Stream.
    Aqui viaja apenas a referência (job_id) e os metadados (dia).
    """

    job_id: str
    dia: int
    filename: str
