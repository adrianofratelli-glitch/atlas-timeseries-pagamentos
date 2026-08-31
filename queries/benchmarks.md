# Measured numbers

Everything here was measured against the demo Atlas cluster (M20 — 4 GB RAM, 2 vCPU,
MongoDB 9.0), shared with other demonstration databases. Nothing is estimated. Raw
output in `bench-results.json`, `bucket-experiment.json` and `../tests/stress-results.json`.

Re-measure rather than copy forward when the cluster, the volume or the reading
interval changes.

## The base

| | |
|---|---:|
| Measurements | **58 820 400** |
| Meters | 19 980 + 444 boundary meters |
| Period | 30 days, one reading per 15 min |
| Load time | 1 292 s (**45 531 measurements/s**, single process) |
| Storage | **464 MB** data + **80 MB** index |
| Bytes per measurement | **7.9** |

The bucket layout (`bucketMaxSpanSeconds: 86400`) was chosen by measurement in
[`../docs/adr/0001-bucketing.md`](../docs/adr/0001-bucketing.md), which predicted
~430 MB from a 7-day sample. The full load came in at 464 MB — the extrapolation held.

## Storage against a plain collection

Same measurements, same day, written twice. `readings_flat` holds one day of the
same data, so the comparison is per measurement, not in absolute size.

| | `readings` (time series) | `readings_flat` (plain) |
|---|---:|---:|
| Measurements | 58 820 400 | 1 960 680 |
| Data | 464.5 MB | 109.2 MB |
| Index | 80.4 MB | 118.2 MB |
| Bytes per measurement (data) | **7.90** | 55.67 |
| Bytes per measurement (with index) | **9.27** | 116.0 |
| Buckets | 612 720 | — |

**7.05× less storage per measurement, 12.52× counting the index.**

The index is where most of the difference lives: 80 MB covering 58.8 M measurements
against 118 MB covering 1.96 M. An index on a time series collection indexes buckets —
612 720 of them here — not measurements, so it is roughly ninety times smaller per
measurement. On a metering base that keeps years of history, that line alone changes
the disk tier.

This is MongoDB against MongoDB. It is a fact about the bucket format, not a claim
about InfluxDB or TimescaleDB — see `../LIMITATIONS.md`.

## Latency

30 runs each, after warm-up. **Network floor: p50 8.5 ms** for a `hello` from the
presenting host — subtract it before calling any of these a database number.

| Query | p50 | p95 | above the floor |
|---|---:|---:|---:|
| Load curve, 1 day, one meter | 11.5 ms | 13.8 ms | 3.0 ms |
| Load curve, 1 day, with `$densify`/`$fill` | 12.2 ms | 12.7 ms | 3.7 ms |
| Load curve, 30 days, one meter | 16.3 ms | 18.1 ms | 7.8 ms |
| Transformer balance, 1 day | 19.2 ms | 22.5 ms | 10.7 ms |
| Transformer balance, 7 days | 69.9 ms | 85.8 ms | 61.4 ms |
| Transformer balance, 30 days | 336.9 ms | 511.3 ms | 328.4 ms |

Reading these honestly:

- **The curve queries are mostly network.** 3 ms of server work over an 8.5 ms round
  trip, and thirty days of data costs 5 ms more than one day. They are evidence that
  the bucket index works, not evidence of raw speed.
- **Gap reconstruction is nearly free.** `$densify` + `$fill` add 0.7 ms to the same
  query. Doing it in the application would cost a round trip per gap plus the transfer
  of the raw series.
- **The balance is the real query.** It touches every meter under the transformer:
  ~45 meters × 96 readings × 30 days ≈ 130 000 measurements unpacked, grouped twice
  and run through `$setWindowFields`, in 337 ms. It scales roughly linearly with the
  window, which is why the demo defaults to 7 days.

### A measurement trap worth knowing

The first bench run, executed immediately after the 58.8 M load finished, reported a
**network floor of 281 ms** and every query proportionally inflated. Nothing was wrong
with the queries — the cluster was still checkpointing the bulk load. Re-measured a few
minutes later on the same data, the floor was back to 8.5 ms.

Benchmarking right after a bulk load measures the load, not the workload. Wait for the
cluster to go quiet, and always measure the floor in the same run.

## Under mixed load

`tests/stress.py`, one analytic client (balance, 7–30 days) for every three interactive
clients (load curve), 12 s per level.

| Clients | rps | interactive p50 | interactive p95 | analytic p50 | refused (429) |
|---:|---:|---:|---:|---:|---:|
| 4 | 140 | 23.4 ms | 34.7 ms | 341 ms | 0 |
| 8 | 260 | 23.8 ms | 36.4 ms | 279 ms | 0 |
| 16 | 386 | 28.8 ms | 52.4 ms | 650 ms | 3 |
| 32 | 439 | 49.8 ms | 80.4 ms | 777 ms | 48 |
| 64 | 451 | 101.7 ms | 144.1 ms | 811 ms | 162 |

No 5xx and no timeout at any level. The point of the table is the two middle columns:
at 64 concurrent clients the analytic path is at 811 ms and the interactive path is
still at 144 ms p95, because `app/services/limits.py` gives the balance three slots and
refuses the excess with a 429 in 750 ms.

Without that bulkhead the analytic queries share the queue and take the interactive
path with them — the same failure the graph PoV measured and fixed the same way.

## Reproducing

```bash
.venv/bin/python queries/bench.py --runs 30          # rewrites bench-results.json
.venv/bin/python queries/bucket_experiment.py        # the ADR 0001 table
.venv/bin/python tests/stress.py --max 64            # the table above
```
