"""Curva de carga de um medidor, com reconstrução de lacuna no próprio pipeline.

`$densify` cria os instantes que faltam e `$fill` preenche os valores. Nenhum laço
em Python percorrendo a série: no instante em que a aplicação faz isso, a tese deste
PoV morre, porque é exatamente o trabalho que se compra um motor dedicado para não
fazer.

Todo ponto reconstruído volta marcado (`filled: true` + método). Uma demo que inventa
leitura de energia para uma distribuidora sem dizer que inventou não é demo, é
passivo.
"""
from __future__ import annotations

from datetime import datetime

from ..config import MAX_POINTS, MAX_TIME_MS
from .client import db, with_retry
from .ranges import label, resolve


def pipeline(meter_id: str, start: datetime | None, end: datetime | None, unit: str,
             size: int, fill: bool) -> list[dict]:
    match: dict = {"meta.meter_id": meter_id}
    if start and end:
        match["ts"] = {"$gte": start, "$lt": end}
    pipe: list[dict] = [
        {"$match": match},
        {"$group": {
            "_id": {"$dateTrunc": {"date": "$ts", "unit": unit, "binSize": size}},
            "kwh": {"$sum": "$kwh"},
            "voltage": {"$avg": "$voltage"},
            "power_factor": {"$avg": "$power_factor"},
            "n": {"$sum": 1},
        }},
        {"$set": {"ts": "$_id", "measured": True}},
        {"$sort": {"ts": 1}},
    ]
    if fill and start and end:
        pipe += [
            {"$densify": {"field": "ts",
                          "range": {"step": size, "unit": unit, "bounds": [start, end]}}},
            {"$fill": {"sortBy": {"ts": 1},
                       "output": {"kwh": {"method": "linear"},
                                  "voltage": {"method": "locf"},
                                  "power_factor": {"method": "locf"}}}},
            {"$set": {"filled": {"$ne": ["$measured", True]},
                      "fill_method": {"$cond": [{"$ne": ["$measured", True]}, "linear", None]}}},
        ]
    else:
        pipe += [{"$set": {"filled": False, "fill_method": None}}]

    pipe += [
        {"$project": {"_id": 0, "ts": 1, "kwh": {"$round": ["$kwh", 4]},
                      "voltage": {"$round": ["$voltage", 1]},
                      "power_factor": {"$round": ["$power_factor", 3]},
                      "filled": 1, "fill_method": 1, "n": {"$ifNull": ["$n", 0]}}},
        {"$limit": MAX_POINTS},
    ]
    return pipe


def load_curve(meter_id: str, days: float, fill: bool, live: bool = False) -> dict:
    if live:
        # Sem faixa e sem $fill: ao vivo não há lacuna a reconstruir, e a TTL de
        # `readings_live` já delimita o que existe.
        # Bins de 5 s: ao vivo o eixo é o relógio real (~1 s por tick), então
        # agrupar por minuto devolvia um ponto só nos primeiros minutos.
        start = end = None
        unit, size = "second", 5
    else:
        start, end, unit, size = resolve(days)
    pipe = pipeline(meter_id, start, end, unit, size, fill)
    colecao = "readings_live" if live else "readings"
    points = with_retry(lambda: list(db()[colecao].aggregate(pipe, maxTimeMS=MAX_TIME_MS)))
    filled = sum(1 for p in points if p.get("filled"))
    return {
        "meter_id": meter_id,
        "live": live,
        "collection": colecao,
        "from": points[0]["ts"] if live and points else start,
        "to": points[-1]["ts"] if live and points else end,
        "granularity": {"unit": unit, "bin_size": size, "label": label(unit, size)},
        "points": points,
        "point_count": len(points),
        "filled_count": filled,
        "truncated": len(points) >= MAX_POINTS,
        "pipeline": pipe,
    }
