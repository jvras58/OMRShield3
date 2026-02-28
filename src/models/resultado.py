"""
models/resultado.py — Modelos de domínio do pipeline de extração.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


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
