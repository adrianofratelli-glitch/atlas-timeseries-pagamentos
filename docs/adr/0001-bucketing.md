# ADR 0001 — Bucket span of the time series collection

**Status:** accepted · **Date:** 2026-08-31 · Measured on the demo Atlas cluster (M20,
4 GB RAM, 2 vCPU, MongoDB 9.0)

## Context

`bucketMaxSpanSeconds` and `bucketRoundingSeconds` are fixed when the collection is
created and cannot be changed afterwards. Getting them wrong means recreating the
collection and rewriting every measurement, which is why this is decided before the
generator produces the full base and before any code depends on it.

The workload: a reading every 15 minutes, 96 per meter per day, meta field of
`{meter_id, transformer_id, feeder_id, phase, kind}`.

## Measured

`queries/bucket_experiment.py`, sample of 7 days × 495 meters + 11 boundary meters =
**339 864 measurements**, loaded five times. 30 runs per query after warm-up. Raw
output in `queries/bucket-experiment.json`.

| Variant | Bucket span | Storage | Index | B/measurement | Ratio¹ | Ingest | Curve 1d | Curve 7d | Balance 1d |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| plain collection | — | 18.45 MB | 18.74 MB | 54.29 | 1.0× | 33 k/s | 9.4 ms | 10.7 ms | **33.2 ms** |
| `granularity: "seconds"` | 1 h | 11.46 MB | 8.96 MB | 33.72 | 1.61× | **6.9 k/s** | 10.0 ms | 13.0 ms | 32.5 ms |
| `granularity: "minutes"` | 24 h | 4.14 MB | 0.59 MB | 12.17 | 4.46× | 50 k/s | 9.6 ms | 9.7 ms | 12.5 ms |
| **`bucketMaxSpanSeconds: 86400`** | 24 h | **2.54 MB** | **0.43 MB** | **7.47** | **7.26×** | **50 k/s** | 9.7 ms | 9.9 ms | **11.4 ms** |
| `bucketMaxSpanSeconds: 604800` | 7 d | 2.34 MB | 0.37 MB | 6.89 | 7.88× | 43 k/s | 9.8 ms | 10.4 ms | 13.0 ms |

¹ storage only, against the plain collection. Counting the index as well, the chosen
variant is **12.5× smaller** than the same data in a plain collection (2.97 MB against
37.19 MB) — the index is where most of it comes from, because an index on a time
series collection indexes buckets, not measurements.

**Network floor: p50 8.2 ms** for a `hello` against this cluster from the same host.
Both curve queries sit within 1.5 ms of that floor in every variant, so they do not
discriminate between variants at this volume — they measure the round trip. The
comparison that decides is the balance query and the storage.

## Findings that changed the decision

**The one-hour bucket is the worst of both worlds.** `granularity: "seconds"` sounds
conservative and is the default reflex for 15-minute data. It gives 4 measurements per
bucket, 1.61× compression, and — the number nobody expects — **7× slower ingestion**
(6.9 k/s against 50 k/s). Twenty-four times more bucket documents to open, fill and
close. This was re-measured with the load order reversed to rule out warm-up bias; the
gap held.

**The seven-day bucket wins storage and loses the query that matters.** 7.88× against
7.26× is 8% less storage, and it costs 14% on the transformer balance (13.0 ms against
11.4 ms) — the query that touches every meter under the transformer and has to unpack
a week of buckets to answer about one day. The demo runs that query live.

**Explicit beats the keyword.** `"minutes"` produces the same 24 h span but 4.46×
against 7.26×, because the server's own rounding leaves the buckets less densely
packed than the explicit rounding does. Same span, 63% more storage.

## Decision

```js
db.createCollection("readings", {
  timeseries: { timeField: "ts", metaField: "meta",
                bucketMaxSpanSeconds: 86400, bucketRoundingSeconds: 86400 },
  expireAfterSeconds: 34560000   // 400 dias
})
```

96 measurements per bucket, one bucket per meter per day. Best balance latency, best
ingestion, within 8% of the best storage, and stated in the schema instead of implied
by a keyword a reader would have to expand mentally.

## Consequences

- The numbers above go into `queries/benchmarks.md` and `docs/briefing/02-mongodb.md`,
  and a customer asking "why that span" gets this table rather than a preference.
- At 7.47 bytes per measurement, the target base of ~57.6 M measurements is around
  **430 MB of storage plus ~75 MB of index** — comfortable on this cluster, which is
  what allows the full 30 days to stay in the demo.
- The curve queries are at the network floor at this volume. Any latency claim about
  them must be re-measured at full volume before it appears in front of a customer;
  `queries/benchmarks.md` is the only place those numbers live.
- Re-run `queries/bucket_experiment.py` if the reading interval changes. A 5-minute
  interval triples the measurements per bucket and moves every row of this table.
