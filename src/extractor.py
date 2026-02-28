"""
extractor.py — Serviço principal de extração sem template.

Orquestra: loader → CPF → auto_detect → Resultado.

O campo `img_alinhada` é preenchido para que a camada de API
possa gerar o grid visual sem re-processar a imagem.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from src.loader import carregar_imagem, carregar_imagem_bytes
from src.auto_detect import detectar_todos
from src.ocr import extrair_cpf
from src.config import N_BLOCOS, N_QUESTOES_POR_BLOCO

log = logging.getLogger(__name__)

QUESTOES_POR_DIA = N_BLOCOS * N_QUESTOES_POR_BLOCO


class Status(Enum):
    OK      = "ok"
    PARCIAL = "parcial"
    FALHOU  = "falhou"


@dataclass
class Resultado:
    cpf:                       Optional[str]        = None
    respostas:                 dict                 = field(default_factory=dict)
    status:                    Status               = Status.FALHOU
    avisos:                    list                 = field(default_factory=list)
    tentativas_cpf:            int                  = 0
    total_questoes_detectadas: int                  = 0
    img_alinhada:              Optional[np.ndarray] = field(default=None, repr=False)


class ExtratorCartao:
    def processar_arquivo(self, img_path: str, dia: int = 1) -> Resultado:
        r = Resultado()
        try:
            img = carregar_imagem(img_path)
        except Exception as e:
            log.error(str(e))
            r.avisos.append(str(e))
            return r
        return self._processar(img, r, dia)

    def processar_bytes(self, data: bytes, dia: int = 1) -> Resultado:
        r = Resultado()
        try:
            img = carregar_imagem_bytes(data)
        except Exception as e:
            log.error(str(e))
            r.avisos.append(str(e))
            return r
        return self._processar(img, r, dia)

    def _processar(self, img: np.ndarray, r: Resultado, dia: int) -> Resultado:
        log.info(f"=== Processando dia {dia} ===")

        r.img_alinhada = img

        # CPF
        cpf, t_cpf = extrair_cpf(img)
        r.cpf            = cpf
        r.tentativas_cpf = t_cpf
        if not cpf:
            r.avisos.append("CPF não detectado.")

        # Respostas
        respostas = detectar_todos(img, dia=dia)
        r.respostas                  = respostas
        r.total_questoes_detectadas  = len(respostas)

        if len(respostas) < QUESTOES_POR_DIA:
            r.avisos.append(
                f"Apenas {len(respostas)}/{QUESTOES_POR_DIA} questoes detectadas."
            )

        if cpf and len(respostas) == QUESTOES_POR_DIA:
            r.status = Status.OK
        elif cpf or len(respostas) > 0:
            r.status = Status.PARCIAL

        return r
