# Measured numbers

Everything here was measured against the demo Atlas cluster (M20 — 4 GB RAM, 2 vCPU,
MongoDB 9.0), shared with other demonstration databases. Nothing is estimated. Raw output
in `bench-results.json`, `bucket-experiment.json`, `cardinality-experiment.json` and
`../tests/stress-results.json`.

Re-measure rather than copy forward when the cluster, the volume or the traffic shape
changes.

## The two decisions that were measured before any code

### Bucket span, and the order events are written in

`queries/bucket_experiment.py` — the same 400 000 events loaded six times.
[`../docs/adr/0001-bucketing.md`](../docs/adr/0001-bucketing.md) has the full table.

| Variant | B/event | Ratio vs plain | Ingest | Health query |
|---|---:|---:|---:|---:|
| plain collection | 52.92 | 1.0× | 28 091/s | 75.2 ms |
| `granularity: "seconds"` | 24.13 | 2.19× | 6 593/s | 32.2 ms |
| `granularity: "minutes"` | 34.16 | 1.55× | 6 211/s | 24.1 ms |
| `bucketMaxSpanSeconds: 3600` | 26.81 | 1.97× | 5 332/s | 32.7 ms |
| `bucketMaxSpanSeconds: 86400` | 33.00 | 1.60× | 6 302/s | **19.2 ms** |
| 86400, written series-contiguous | **10.90** | **4.86×** | **12 308/s** | 20.7 ms |

Write order, isolated on 1 000 000 events over 1 296 routes:

| Writer | B/event | Ingest |
|---|---:|---:|
| generation order, 25 k batches | 33.79 | 8 672/s |
| sorted inside each 25 k batch | 29.88 | 7 905/s |
| sorted globally | **16.84** | **11 733/s** |

**Two numbers to keep honest about.** The plain collection ingests 4.5× faster than the
time series collection — time series trades write throughput for storage and query
shape. And the 2× from global sorting only partly survives in a streaming writer:
buffering 300 events per route on the real load gave **22.86 B/event against 24.26**, six
percent, because a route's bucket is still filled across several flushes. The saving
scales with how much of a bucket the writer delivers per call.

### Where the account goes

`queries/cardinality_experiment.py` — 400 000 events over 2 000 000 accounts, both models
from the identical document list.
[`../docs/adr/0002-cardinalidade.md`](../docs/adr/0002-cardinalidade.md).

| | account as field + index | account inside `meta` |
|---|---:|---:|
| Buckets | **19 127** | 399 924 |
| Events per bucket | 20.9 | **1.0** |
| Index | **3.59 MB** | 98.38 MB |
| Bytes per event | **29.84** | 85.27 |
| Ingestion | **9 143/s** | 1 255/s |
| Account velocity (p50) | **517 ms** | 618 ms |
| p99 per provider (p50) | **427 ms** | 731 ms |

The account in the meta field costs 2.9× the storage, **27× the index** and 7× the write
throughput — and it is slower at the per-account query it exists to accelerate. The
absolute latencies in this table were measured while the cluster was also loading the
main dataset; they are valid as a comparison between the two models, which is what the
ADR needs.

## The base

| | |
|---|---:|
| Events | *(re-measured after the current load; the loader prints the final count)* |
| Providers | 44 across PIX, card and TED |
| Routes (`meta` combinations) | ~2 900 |
| Accounts | 2 000 000 |
| Period | 7 days at ~75 events/s average |
| Ingestion, 4 partitioned writers | ~15 600/s |
| Bytes per event | 22.86 |

## Query latency

> **Pending.** The full-volume run of `queries/bench.py` is executed after the current
> load finishes and the cluster goes quiet. Until this section carries the table, no
> query latency from this PoV should appear in front of a customer.
>
> The reason for the wait is itself a measured finding: a bench run started immediately
> after a bulk load reported a **281 ms network floor** and every query inflated to
> match. Re-measured minutes later on a quiet cluster, the floor was 8.5 ms.
> Benchmarking right after a bulk load measures the load, not the workload.

Reproduce with:

```bash
.venv/bin/python queries/bench.py --runs 20
```

The output reports the network floor in the same run, and every latency should be read
against it — several of these queries sit within a few milliseconds of the round trip.

## Under mixed load

> **Pending** the same full-volume run. `tests/stress.py` drives three interactive
> clients (account velocity) for every analytic one (provider health) and reports whether
> the analytic path takes the interactive path down with it. The bulkhead in
> `backend/app/services/limits.py` gives the analytic queue three slots and refuses the
> excess with a `429` after 750 ms.

```bash
.venv/bin/python tests/stress.py --max 64
```
