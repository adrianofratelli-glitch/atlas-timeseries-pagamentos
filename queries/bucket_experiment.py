"""ADR 0001 — mede o span de bucket em vez de escolher por preferência.

Carrega a mesma amostra de 7 dias em quatro variantes de coleção time series e em
uma coleção normal, e mede o que o parâmetro decide de fato: armazenamento, curva
de um dia, curva de sete dias e balanço do transformador (a consulta mais exposta
a um bucket grande, porque toca todos os medidores abaixo dele).

`bucketMaxSpanSeconds` não pode ser alterado depois da criação da coleção. Por isso
esta medição vem antes do backend existir.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data-generator"))
import common  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VARIANTS = ["seconds", "minutes", "span1d", "span7d"]


def load(db_name: str, days: int, transformers: int, drop: bool):
    py = os.path.join(ROOT, ".venv", "bin", "python")
    gen = os.path.join(ROOT, "data-generator", "generate_readings.py")
    for v in VARIANTS + ["flat"]:
        col = f"probe_{v}"
        d = common.db(db_name)
        if not drop and col in d.list_collection_names() and d[col].estimated_document_count():
            print(f"  {col:16} já carregada, pulando")
            continue
        cmd = [py, gen, "--db", db_name, "--collection", col, "--days", str(days),
               "--drop"]
        if v == "flat":
            cmd += ["--flat", "--variant", "span1d"]
        else:
            cmd += ["--variant", v]
        if transformers:
            cmd += ["--transformers", str(transformers)]
        t0 = time.time()
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            sys.exit(out.stdout + out.stderr)
        print(f"  {col:16} {time.time() - t0:6.1f}s   {out.stdout.strip().splitlines()[-1]}")


def index_all(d):
    for v in VARIANTS + ["flat"]:
        col = d[f"probe_{v}"]
        col.create_index([("meta.meter_id", 1), ("ts", 1)])
        col.create_index([("meta.transformer_id", 1), ("ts", 1)])


def curve_pipeline(meter_id, start, end, unit):
    return [
        {"$match": {"meta.meter_id": meter_id, "ts": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": {"$dateTrunc": {"date": "$ts", "unit": unit}},
                    "kwh": {"$sum": "$kwh"},
                    "voltage": {"$avg": "$voltage"},
                    "n": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]


def balance_pipeline(transformer_id, start, end):
    return [
        {"$match": {"meta.transformer_id": transformer_id, "ts": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": {"h": {"$dateTrunc": {"date": "$ts", "unit": "hour"}},
                            "kind": "$meta.kind"},
                    "kwh": {"$sum": "$kwh"}}},
        {"$group": {"_id": "$_id.h",
                    "entregue": {"$sum": {"$cond": [{"$eq": ["$_id.kind", "fronteira"]},
                                                    "$kwh", 0]}},
                    "registrado": {"$sum": {"$cond": [{"$eq": ["$_id.kind", "medidor"]},
                                                      "$kwh", 0]}}}},
        {"$addFields": {"gap_kwh": {"$subtract": ["$entregue", "$registrado"]},
                        "gap_pct": {"$multiply": [100, {"$cond": [
                            {"$gt": ["$entregue", 0]},
                            {"$subtract": [1, {"$divide": ["$registrado", "$entregue"]}]}, 0]}]}}},
        {"$sort": {"_id": 1}},
    ]


def timed(col, pipeline, runs):
    for _ in range(3):
        list(col.aggregate(pipeline))
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        list(col.aggregate(pipeline))
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {"p50": round(statistics.median(samples), 1),
            "p95": round(samples[int(len(samples) * 0.95) - 1], 1),
            "min": round(samples[0], 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="energia_medicao_sample")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--transformers", type=int, default=0)
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--skip-load", action="store_true")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()

    d = common.db(args.db)
    if not args.skip_load:
        print("carregando variantes:")
        load(args.db, args.days, args.transformers, args.drop)
    print("\níndices...")
    index_all(d)

    meter = d.meters.find_one({"register_factor": 1.0}, sort=[("meter_id", 1)])
    transformer = d.transformers.find_one(sort=[("transformer_id", 1)])
    end = common.utc_midnight(datetime.now(timezone.utc))
    start = end - timedelta(days=args.days)
    day_start = end - timedelta(days=1)

    rows = []
    flat_storage = None
    for v in ["flat"] + VARIANTS:
        name = f"probe_{v}"
        col = d[name]
        st = next(col.aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
        docs = col.estimated_document_count()
        # Em coleção time series, storageSize é o bucket comprimido; totalSize inclui índices.
        row = {
            "variant": v,
            "docs": docs,
            "storage_mb": round(st["storageSize"] / 1e6, 2),
            "index_mb": round(st.get("totalIndexSize", 0) / 1e6, 2),
            "total_mb": round((st["storageSize"] + st.get("totalIndexSize", 0)) / 1e6, 2),
            "bytes_per_measurement": round(st["storageSize"] / max(docs, 1), 2),
            "buckets": st.get("count") if v != "flat" else None,
            "curve_1d": timed(col, curve_pipeline(meter["meter_id"], day_start, end, "hour"),
                              args.runs),
            "curve_7d": timed(col, curve_pipeline(meter["meter_id"], start, end, "day"),
                              args.runs),
            "balance_1d": timed(col, balance_pipeline(transformer["transformer_id"],
                                                      day_start, end), args.runs),
        }
        if v == "flat":
            flat_storage = row["storage_mb"]
        row["ratio_vs_flat"] = round(flat_storage / row["storage_mb"], 2) if row["storage_mb"] else None
        rows.append(row)

    print(f"\namostra: {args.days} dias · {d.meters.count_documents({})} medidores · "
          f"{rows[0]['docs']:,} medições\n")
    head = f'{"variante":10} {"armazen.":>10} {"índice":>9} {"B/medição":>10} {"ratio":>7} ' \
           f'{"curva 1d":>10} {"curva 7d":>10} {"balanço 1d":>11}'
    print(head)
    print("-" * len(head))
    for r in rows:
        print(f'{r["variant"]:10} {r["storage_mb"]:9.2f}M {r["index_mb"]:8.2f}M '
              f'{r["bytes_per_measurement"]:10.2f} {str(r["ratio_vs_flat"]) + "x":>7} '
              f'{r["curve_1d"]["p50"]:9.1f}ms {r["curve_7d"]["p50"]:9.1f}ms '
              f'{r["balance_1d"]["p50"]:10.1f}ms')

    out = os.path.join(ROOT, "queries", "bucket-experiment.json")
    with open(out, "w") as fh:
        json.dump({"measured_at": datetime.now(timezone.utc).isoformat(),
                   "db": args.db, "days": args.days, "runs": args.runs,
                   "meter": meter["meter_id"], "transformer": transformer["transformer_id"],
                   "rows": rows}, fh, indent=2)
    print(f"\n{out}")


if __name__ == "__main__":
    main()
