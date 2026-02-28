"""
services/cartao_service.py — Serviço principal de extração.

Orquestra: image_io → ocr → detection → Resultado.

Exporta:
  ExtratorCartao
"""

import logging

import numpy as np

from src.infrastructure.image_io import carregar_imagem, carregar_imagem_bytes
from src.core.detection import detectar_todos
from src.core.ocr import extrair_cpf
from src.models.resultado import Resultado, Status
from src.settings.config import settings

log = logging.getLogger(__name__)


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

        cpf, t_cpf = extrair_cpf(img)
        r.cpf = cpf
        r.tentativas_cpf = t_cpf
        if not cpf:
            r.avisos.append("CPF não detectado.")

        respostas = detectar_todos(img, dia=dia)
        r.respostas = respostas
        r.total_questoes_detectadas = len(respostas)

        if len(respostas) < settings.QUESTOES_POR_DIA:
            r.avisos.append(
                f"Apenas {len(respostas)}/{settings.QUESTOES_POR_DIA} "
                "questoes detectadas."
            )

        if cpf and len(respostas) == settings.QUESTOES_POR_DIA:
            r.status = Status.OK
        elif cpf or len(respostas) > 0:
            r.status = Status.PARCIAL

        return r
