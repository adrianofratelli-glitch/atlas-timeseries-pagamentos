"""Medições no volume cheio. Regrava queries/bench-results.json.

Toda latência que aparece na frente de um cliente sai daqui, medida contra o
cluster real, com o piso de rede medido junto — sem ele, "9,7 ms" parece
desempenho de banco quando é, quase inteiro, ida e volta de rede.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data-generator"))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import common  # noqa: E402


def percentis(amostras: list[float]) -> dict:
    amostras = sorted(amostras)
    return {
        "p50": round(statistics.median(amostras), 1),
        "p95": round(amostras[max(int(len(amostras) * 0.95) - 1, 0)], 1),
        "min": round(amostras[0], 1),
        "max": round(amostras[-1], 1),
    }


def medir(fn, runs: int) -> dict:
    for _ in range(3):
        fn()
    amostras = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        amostras.append((time.perf_counter() - t0) * 1000)
    return percentis(amostras)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    os.environ.setdefault("MONGODB_DB", args.db or os.getenv("MONGODB_DB", "energia_medicao"))
    from app.db import balance, curve  # noqa: E402  (depende do MONGODB_DB acima)
    from app.db.ranges import anchor  # noqa: E402

    d = common.db(args.db)
    info = d.dataset_info.find_one({"_id": "readings"}) or {}
    medidor = d.meters.find_one({"register_factor": 1.0}, sort=[("meter_id", 1)])
    cenario = d.loss_scenarios.find_one(sort=[("expected_gap_pct", -1)])
    end = anchor()

    resultados = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "database": os.environ["MONGODB_DB"],
        "measurements": info.get("measurements") or d.readings.estimated_document_count(),
        "meters": info.get("meters"),
        "days": info.get("days"),
        "runs": args.runs,
        "network_floor_ms": None,
        "cases": {},
    }

    resultados["network_floor_ms"] = medir(lambda: d.command("hello"), args.runs)

    casos = {
        "curva_1_dia": lambda: curve.load_curve(medidor["meter_id"], 1, False),
        "curva_1_dia_preenchida": lambda: curve.load_curve(medidor["meter_id"], 1, True),
        "curva_30_dias": lambda: curve.load_curve(medidor["meter_id"], 30, False),
        "balanco_1_dia": lambda: balance.transformer_balance(cenario["transformer_id"], 1),
        "balanco_7_dias": lambda: balance.transformer_balance(cenario["transformer_id"], 7),
        "balanco_30_dias": lambda: balance.transformer_balance(cenario["transformer_id"], 30),
    }
    for nome, fn in casos.items():
        print(f"  {nome} ...", flush=True)
        resultados["cases"][nome] = medir(fn, args.runs)

    st = next(d.readings.aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
    resultados["storage"] = {
        "storage_bytes": st["storageSize"],
        "index_bytes": st.get("totalIndexSize", 0),
        "bytes_per_measurement": round(st["storageSize"] / max(resultados["measurements"], 1), 2),
        "buckets": (st.get("timeseries") or {}).get("bucketCount"),
    }

    out = os.path.join(ROOT, "queries", "bench-results.json")
    with open(out, "w") as fh:
        json.dump(resultados, fh, indent=2)

    piso = resultados["network_floor_ms"]["p50"]
    print(f'\n{resultados["measurements"]:,} medições · {resultados["meters"]} medidores · '
          f'{resultados["days"]} dias · piso de rede p50 {piso} ms\n')
    print(f'{"consulta":28} {"p50":>8} {"p95":>8} {"acima do piso":>15}')
    print("-" * 63)
    for nome, v in resultados["cases"].items():
        print(f'{nome:28} {v["p50"]:7.1f}ms {v["p95"]:7.1f}ms {v["p50"] - piso:14.1f}ms')
    print(f'\narmazenamento: {resultados["storage"]["bytes_per_measurement"]} B/medição, '
          f'{resultados["storage"]["storage_bytes"] / 1e6:,.0f} MB + '
          f'{resultados["storage"]["index_bytes"] / 1e6:,.0f} MB de índice')
    print(out)


if __name__ == "__main__":
    main()
