"""
worker/consumer.py — Worker FastStream para processamento assíncrono de cartões.

Consome mensagens do Redis Stream 'omr.batch', processa cada cartão
e salva o resultado no GridCache (Redis) para a API recuperar.

Execução:
  faststream run src.worker.consumer:app

  ou via Docker Compose (serviço 'worker' no compose.yml).

Escala horizontal:
  Basta adicionar mais réplicas do serviço worker — cada instância
  participa do consumer group e recebe mensagens distintas.
"""

import logging

from faststream.redis import RedisMessage

from src.infrastructure.broker import broker
from src.infrastructure.cache import GridCache, make_grid_cache
from src.infrastructure.redis_client import get_redis
from src.models.resultado import CartaoJob
from src.services.cartao_service import ExtratorCartao

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

_extrator = ExtratorCartao()


def _get_cache() -> GridCache:
    return make_grid_cache(get_redis())


# ── Subscriber ────────────────────────────────────────────────────────────────


@broker.subscriber(
    stream="omr.batch",
    group="omr-workers",
    consumer="omr-worker",
)
async def processar_cartao_job(job: CartaoJob, msg: RedisMessage) -> None:
    """
    Processa um CartaoJob consumido do Redis Stream.

    Fluxo:
      1. Recupera imagem raw do Redis (temp:{job_id})
      2. Processa: alinhar → detectar → OCR
      3. Salva resultado no GridCache (grid:{job_id}:img + meta)
      4. Remove a imagem temporária
      5. ACK automático pelo FastStream (mensagem removida da fila pendente)

    Em caso de erro irrecuperável, marca o job como "failed" no cache
    para que o cliente não fique em polling infinito.
    """
    log.info(f"[Worker] Recebido job_id={job.job_id} arquivo={job.filename}")

    cache = _get_cache()

    img_bytes = cache.get_temp(job.job_id)
    if img_bytes is None:
        log.error(
            f"[Worker] Imagem temporária não encontrada para job_id={job.job_id} "
            "(expirou ou nunca foi salva). Descartando."
        )
        await msg.ack()
        return

    try:
        resultado = _extrator.processar_bytes(bytes(img_bytes), dia=job.dia)
    except Exception as exc:
        log.exception(f"[Worker] Erro ao processar job_id={job.job_id}: {exc}")
        cache.set_failed(job.job_id, avisos=[f"Erro interno: {exc}"])
        cache.del_temp(job.job_id)
        await msg.ack()
        return

    if resultado.img_alinhada is not None:
        cache.set(
            job.job_id,
            resultado.img_alinhada,
            resultado.respostas,
            job.dia,
            cpf=resultado.cpf,
            avisos=resultado.avisos,
        )
        log.info(
            f"[Worker] Concluído job_id={job.job_id} "
            f"status={resultado.status.value} "
            f"questoes={resultado.total_questoes_detectadas}"
        )
    else:
        cache.set_failed(
            job.job_id, avisos=resultado.avisos or ["Falha no alinhamento."]
        )
        log.warning(f"[Worker] job_id={job.job_id} falhou no alinhamento.")

    cache.del_temp(job.job_id)
    await msg.ack()
