"""
infrastructure/broker.py — Instâncias compartilhadas do FastStream/RedisBroker.

Centraliza a criação do broker e da app para que tanto o worker
quanto outros módulos possam importar de um único lugar.
"""

from faststream import FastStream
from faststream.redis import RedisBroker

from src.settings.config import settings

broker = RedisBroker(settings.REDIS_URL)
app = FastStream(broker)
