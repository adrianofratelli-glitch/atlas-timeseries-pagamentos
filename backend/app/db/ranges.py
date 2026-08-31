"""Faixa pedida pelo cliente e granularidade escolhida pelo servidor.

O cliente pede um intervalo; quem decide o $dateTrunc é o servidor. Um navegador
plotando três milhões de pontos é um navegador que parou, e trocar a granularidade
em silêncio embaixo do apresentador produz pergunta que ninguém responde no palco —
por isso a granularidade escolhida volta no payload.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import MAX_RANGE_DAYS, READING_INTERVAL_MINUTES
from .client import db

UNITS = {
    "second": 1,
    "minute": READING_INTERVAL_MINUTES,
    "hour": 60,
    "day": 60 * 24,
}


class RangeError(ValueError):
    """Faixa inválida.

    Erro de domínio, não HTTP: a camada de dados não importa fastapi, do mesmo
    modo que nenhuma rota importa pymongo. `main.py` traduz em 422. Sem isso, o
    bench e qualquer script fora do venv do backend precisariam do framework
    inteiro para calcular um intervalo.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail
        self.max_range_days = MAX_RANGE_DAYS


_ANCHOR: datetime | None = None


def anchor() -> datetime:
    """Fim do dataset, não o relógio.

    A carga cobre [hoje-N, última meia-noite). Ancorar no relógio fazia uma janela
    de 7 dias devolver 146 horas em vez de 168 — as horas que faltavam não existem
    no dado. Lido uma vez de `dataset_info`, gravado pelo gerador.
    """
    global _ANCHOR
    if _ANCHOR is None:
        info = db().dataset_info.find_one({"_id": "readings"})
        last = info.get("last_ts") if info else None
        _ANCHOR = last.replace(tzinfo=timezone.utc) if last else \
            datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return _ANCHOR


def resolve(days: float, end: datetime | None = None) -> tuple[datetime, datetime, str, int]:
    """Devolve (início, fim, unidade, bin_size) para a faixa pedida."""
    if days <= 0:
        raise RangeError("faixa deve ser positiva")
    if days > MAX_RANGE_DAYS:
        raise RangeError(f"faixa acima do teto de {MAX_RANGE_DAYS} dias")

    end = end or anchor()
    start = end - timedelta(days=days)

    # Alvo: manter a série na casa das centenas de pontos, qualquer que seja a faixa.
    if days <= 2:
        unit, size = "minute", READING_INTERVAL_MINUTES
    elif days <= 14:
        unit, size = "hour", 1
    else:
        unit, size = "day", 1
    return start, end, unit, size


def label(unit: str, size: int) -> str:
    return {"second": f"{size} s", "minute": f"{size} min",
            "hour": "1 hora", "day": "1 dia"}[unit]
