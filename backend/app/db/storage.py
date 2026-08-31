"""Comparação de armazenamento: a mesma medição em coleção time series e normal.

`readings_flat` guarda um dia; `readings` guarda trinta. Comparar tamanho absoluto
entre as duas seria desonesto, então a comparação é por medição — bytes por medição
e a razão entre elas — e o payload diz quantos dias cada coleção cobre.
"""
from __future__ import annotations

from .client import db, with_retry


def _stats(name: str) -> dict | None:
    d = db()
    try:
        st = next(d[name].aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
    except Exception:
        return None
    docs = st.get("count") or d[name].estimated_document_count()
    if not docs:
        return None
    storage = st.get("storageSize", 0)
    index = st.get("totalIndexSize", 0)
    return {
        "collection": name,
        "documents": docs,
        "storage_bytes": storage,
        "index_bytes": index,
        "total_bytes": storage + index,
        "bytes_per_measurement": round(storage / docs, 2),
        "total_bytes_per_measurement": round((storage + index) / docs, 2),
        "timeseries": bool(st.get("timeseries")),
        "buckets": (st.get("timeseries") or {}).get("bucketCount"),
    }


def comparison() -> dict:
    ts = with_retry(lambda: _stats("readings"))
    flat = with_retry(lambda: _stats("readings_flat"))
    if not ts or not flat:
        return {"available": False,
                "reason": "readings_flat ausente — rode o gerador com --flat"}
    return {
        "available": True,
        "timeseries": ts,
        "flat": flat,
        "storage_ratio": round(flat["bytes_per_measurement"] / ts["bytes_per_measurement"], 2),
        "total_ratio": round(
            flat["total_bytes_per_measurement"] / ts["total_bytes_per_measurement"], 2),
        "note": "razão por medição; as coleções cobrem períodos diferentes de propósito",
    }
