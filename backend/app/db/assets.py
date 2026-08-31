"""Cadastro: alimentadores, transformadores, medidores, cenários plantados."""
from __future__ import annotations

from ..config import MAX_TIME_MS
from .client import db, with_retry

# `register_factor` fica de fora de propósito: é a verdade de terra do furto. Quem
# precisa dela é /api/scenarios, e por lá o payload diz que é verdade de terra.
PROJECT_METER = {"_id": 0, "meter_id": 1, "transformer_id": 1, "feeder_id": 1,
                 "phase": 1, "customer_class": 1, "kwh_dia_base": 1, "tariff": 1,
                 "installed_at": 1, "under_investigation": 1, "location": 1,
                 "seeded_outage": 1, "seeded_voltage_sag": 1}


def transformers(limit: int = 200) -> list[dict]:
    """Transformadores com o cenário plantado anexado, quando houver."""
    pipe = [
        {"$lookup": {"from": "loss_scenarios", "localField": "transformer_id",
                     "foreignField": "transformer_id", "as": "scenario"}},
        {"$set": {"scenario": {"$first": "$scenario"}}},
        {"$lookup": {"from": "meters", "localField": "transformer_id",
                     "foreignField": "transformer_id", "as": "m",
                     "pipeline": [{"$count": "n"}]}},
        {"$set": {"meter_count": {"$ifNull": [{"$first": "$m.n"}, 0]}}},
        {"$project": {"_id": 0, "m": 0}},
        {"$sort": {"transformer_id": 1}},
        {"$limit": limit},
    ]
    return with_retry(lambda: list(db().transformers.aggregate(pipe, maxTimeMS=MAX_TIME_MS)))


def meter(meter_id: str) -> dict | None:
    return with_retry(lambda: db().meters.find_one({"meter_id": meter_id}, PROJECT_METER))


def meters_of(transformer_id: str, limit: int = 500) -> list[dict]:
    return with_retry(lambda: list(
        db().meters.find({"transformer_id": transformer_id}, PROJECT_METER)
        .sort("meter_id", 1).limit(limit)))


def scenarios() -> list[dict]:
    """Verdade de terra. A demo verifica o balanço contra ela, nunca contra a sorte."""
    return with_retry(lambda: list(db().loss_scenarios.find({}, {"_id": 0})
                                   .sort("expected_gap_pct", -1)))


def demo_meters() -> dict:
    """Medidores dos eventos plantados, para o roteiro não depender de procurar."""
    d = db()
    outage = d.meters.find_one({"seeded_outage": {"$exists": True}}, PROJECT_METER)
    sag = d.meters.find_one({"seeded_voltage_sag": {"$exists": True}}, PROJECT_METER)
    fraud = d.meters.find_one({"register_factor": {"$lt": 1.0}}, PROJECT_METER)
    return {"outage": outage, "voltage_sag": sag, "fraude": fraud}
