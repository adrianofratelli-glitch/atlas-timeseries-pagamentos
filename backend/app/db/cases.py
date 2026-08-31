"""Abertura de investigação: uma transação, três escritas.

Metade desse estado é pior que nenhum — medidor marcado sem caso por trás é achado
de auditoria. O evento que acorda o change stream é a própria marcação, não uma
escrita sintética numa coleção paralela.

O backend nunca escreve em `readings`. Medição é fato de campo; caso é opinião sobre
ela, e mora em outro lugar.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from ..config import FIELD_INSPECTION_COST, KWH_TARIFF
from .client import client, db, with_retry


def open_case(meter_id: str, transformer_id: str, gap_kwh: float, gap_pct: float,
              windows: int, opened_by: str, note: str | None = None) -> dict:
    d = db()
    meter = d.meters.find_one({"meter_id": meter_id})
    if not meter:
        raise ValueError(f"medidor {meter_id} não existe")
    if meter.get("under_investigation"):
        raise DuplicateKeyError(f"medidor {meter_id} já está em investigação")

    case_id = f"INV-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(timezone.utc)
    # Não é medição: é o número do cliente, e a tela rotula como tal.
    energia_perdida = round(gap_kwh, 2)
    valor = round(energia_perdida * KWH_TARIFF, 2)

    doc = {
        "case_id": case_id,
        "meter_id": meter_id,
        "transformer_id": transformer_id,
        "status": "aberto",
        "opened_at": now,
        "opened_by": opened_by,
        "note": note,
        "evidence": {"gap_kwh": energia_perdida, "gap_pct": round(gap_pct, 2),
                     "windows_above_threshold": windows},
        "estimativa": {"energia_kwh": energia_perdida, "valor": valor,
                       "custo_inspecao": FIELD_INSPECTION_COST,
                       "base": "tarifa da classe do medidor, informada pelo cliente"},
    }

    def run():
        with client().start_session() as session:
            with session.start_transaction():
                d.meters.update_one(
                    {"meter_id": meter_id, "under_investigation": {"$ne": True}},
                    {"$set": {"under_investigation": True, "case_id": case_id,
                              "flagged_at": now}},
                    session=session)
                # insert_one injeta _id no dicionário original; devolver isso rende
                # ObjectId não serializável e um 500 depois do commit.
                d.investigations.insert_one(dict(doc), session=session)
                # A marcação é o evento. O listener observa `investigations`, não a
                # coleção time series: lá o change stream dispara por medição.
                d.meters.update_one(
                    {"meter_id": meter_id},
                    {"$set": {"last_event": {"kind": "caso_aberto", "case_id": case_id,
                                             "at": now}}},
                    session=session)
        return doc

    return with_retry(run)


def close_case(case_id: str, outcome: str, by: str) -> dict | None:
    d = db()
    now = datetime.now(timezone.utc)

    def run():
        with client().start_session() as session:
            with session.start_transaction():
                case = d.investigations.find_one_and_update(
                    {"case_id": case_id, "status": "aberto"},
                    {"$set": {"status": "encerrado", "outcome": outcome,
                              "closed_at": now, "closed_by": by}},
                    return_document=True, session=session)
                if not case:
                    return None
                d.meters.update_one({"meter_id": case["meter_id"]},
                                    {"$set": {"under_investigation": False},
                                     "$unset": {"case_id": ""}},
                                    session=session)
                return case

    return with_retry(run)


def recent(limit: int = 50) -> list[dict]:
    return with_retry(lambda: list(db().investigations.find({}, {"_id": 0})
                                   .sort("opened_at", -1).limit(limit)))


def reset_demo() -> dict:
    """Volta o cenário ao estado inicial. O roteiro roda mais de uma vez por dia."""
    d = db()
    cases = d.investigations.delete_many({})
    meters = d.meters.update_many({"under_investigation": True},
                                  {"$set": {"under_investigation": False},
                                   "$unset": {"case_id": "", "last_event": "",
                                              "flagged_at": ""}})
    alerts = d.loss_alerts.delete_many({})
    return {"cases_removidos": cases.deleted_count,
            "medidores_liberados": meters.modified_count,
            "alertas_removidos": alerts.deleted_count}
