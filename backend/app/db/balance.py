"""Balanço energético do transformador: entregue × registrado.

O medidor de fronteira grava o que foi entregue; os medidores abaixo gravam o que
registraram. A diferença é perda — técnica (aquecimento, rede secundária) mais não
técnica (furto, adulteração). `$setWindowFields` dá a média móvel, e um gap acima do
limiar por N janelas seguidas é suspeita, não certeza: o transformador de controle
tem perda técnica alta e não pode abrir caso.
"""
from __future__ import annotations

from datetime import datetime

from ..config import LOSS_MIN_WINDOWS, LOSS_THRESHOLD_PCT, MAX_POINTS, MAX_TIME_MS
from .client import db, with_retry
from .ranges import label, resolve


def pipeline(transformer_id: str, start: datetime | None, end: datetime | None,
             unit: str, size: int, window: int) -> list[dict]:
    # Ao vivo não filtra por faixa: a TTL de `readings_live` já limita o que existe
    # lá, e ancorar no relógio esconderia o dado simulado, que corre adiantado.
    match: dict = {"meta.transformer_id": transformer_id}
    if start and end:
        match["ts"] = {"$gte": start, "$lt": end}
    return [
        {"$match": match},
        {"$group": {
            "_id": {"t": {"$dateTrunc": {"date": "$ts", "unit": unit, "binSize": size}},
                    "kind": "$meta.kind"},
            "kwh": {"$sum": "$kwh"},
        }},
        {"$group": {
            "_id": "$_id.t",
            "entregue": {"$sum": {"$cond": [{"$eq": ["$_id.kind", "fronteira"]}, "$kwh", 0]}},
            "registrado": {"$sum": {"$cond": [{"$eq": ["$_id.kind", "medidor"]}, "$kwh", 0]}},
        }},
        {"$set": {"ts": "$_id",
                  "gap_kwh": {"$subtract": ["$entregue", "$registrado"]},
                  "gap_pct": {"$cond": [
                      {"$gt": ["$entregue", 0]},
                      {"$multiply": [100, {"$subtract": [
                          1, {"$divide": ["$registrado", "$entregue"]}]}]},
                      0]}}},
        {"$setWindowFields": {
            "sortBy": {"ts": 1},
            "output": {
                "gap_pct_movel": {"$avg": "$gap_pct",
                                  "window": {"documents": [-(window - 1), 0]}},
                "gap_kwh_acumulado": {"$sum": "$gap_kwh",
                                      "window": {"documents": ["unbounded", "current"]}},
            }}},
        {"$set": {"acima_do_limiar": {"$gt": ["$gap_pct_movel", LOSS_THRESHOLD_PCT]}}},
        {"$sort": {"ts": 1}},
        {"$project": {"_id": 0, "ts": 1,
                      "entregue": {"$round": ["$entregue", 3]},
                      "registrado": {"$round": ["$registrado", 3]},
                      "gap_kwh": {"$round": ["$gap_kwh", 3]},
                      "gap_pct": {"$round": ["$gap_pct", 2]},
                      "gap_pct_movel": {"$round": ["$gap_pct_movel", 2]},
                      "gap_kwh_acumulado": {"$round": ["$gap_kwh_acumulado", 2]},
                      "acima_do_limiar": 1}},
        {"$limit": MAX_POINTS},
    ]


def transformer_balance(transformer_id: str, days: float, live: bool = False) -> dict:
    if live:
        # Bins de 5 s: ao vivo o eixo é o relógio real (~1 s por tick), então
        # agrupar por minuto devolvia um ponto só nos primeiros minutos.
        start = end = None
        unit, size = "second", 5
    else:
        start, end, unit, size = resolve(days)
    window = LOSS_MIN_WINDOWS
    pipe = pipeline(transformer_id, start, end, unit, size, window)
    colecao = "readings_live" if live else "readings"
    rows = with_retry(lambda: list(db()[colecao].aggregate(pipe, maxTimeMS=MAX_TIME_MS)))

    # Suspeita = média móvel acima do limiar por LOSS_MIN_WINDOWS janelas seguidas.
    # Um pico isolado é ruído de medição; o que acusa furto é gap que não volta.
    streak = best = 0
    for r in rows:
        streak = streak + 1 if r["acima_do_limiar"] else 0
        best = max(best, streak)

    entregue = sum(r["entregue"] for r in rows)
    registrado = sum(r["registrado"] for r in rows)
    gap_pct = (1 - registrado / entregue) * 100 if entregue else 0.0

    return {
        "transformer_id": transformer_id,
        "live": live,
        "collection": colecao,
        "from": rows[0]["ts"] if live and rows else start,
        "to": rows[-1]["ts"] if live and rows else end,
        "granularity": {"unit": unit, "bin_size": size, "label": label(unit, size)},
        "points": rows,
        "totals": {"entregue_kwh": round(entregue, 2),
                   "registrado_kwh": round(registrado, 2),
                   "gap_kwh": round(entregue - registrado, 2),
                   "gap_pct": round(gap_pct, 2)},
        "threshold_pct": LOSS_THRESHOLD_PCT,
        "min_windows": window,
        "longest_streak": best,
        "suspeito": best >= window,
        "pipeline": pipe,
    }
