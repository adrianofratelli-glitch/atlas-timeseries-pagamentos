# 02 — MongoDB

What runs against the cluster. The modelling reasoning, including why the asset
registry stays out of the measurement document, is in
[`schema/collections.md`](../../schema/collections.md).

## Collections

| Collection | Type | Role | Source |
|---|---|---|---|
| `readings` | **time series** | measurement every 15 min per meter and per boundary meter | `generate_readings.py` |
| `readings_flat` | normal | one day of the same data, for the storage comparison | idem |
| `meters` | normal | the asset: address, class, tariff, install date, `location` | `generate_assets.py` |
| `transformers` | normal | transformer, its feeder, nominal capacity, boundary meter | idem |
| `loss_scenarios` | normal | ground truth of the seeded non-technical loss | idem |
| `investigations` | normal | cases opened by the ACID transaction | backend |
| `loss_alerts` | normal | change stream fires | backend |
| `dataset_info` | normal | first and last measurement of each load | `generate_readings.py` |

### The measurement

```js
db.createCollection("readings", {
  timeseries: { timeField: "ts", metaField: "meta",
                bucketMaxSpanSeconds: 86400, bucketRoundingSeconds: 86400 },
  expireAfterSeconds: 34560000        // 400 dias
})
```

```js
{
  ts: ISODate("2026-08-31T14:15:00Z"),
  meta: { meter_id: "MED-0031482", transformer_id: "TR-00417",
          feeder_id: "AL-021", phase: "B", kind: "medidor" },   // ou "fronteira"
  kwh: 0.412,            // consumption in the 15-minute interval
  voltage: 218.6,
  current: 1.94,
  power_factor: 0.93,
  quality: "ok"          // ok | estimated | missing
}
```

Four decisions in that document, each of which has cost someone a rewrite:

- **`meta` is identity only.** Tariff and customer class are mutable and live in
  `meters`. A mutable meta field silently starts a parallel bucket series when it
  changes — see invariant 1 in `01-arquitetura.md`.
- **`kwh` is the interval, not the register.** Storing the cumulative register would
  force every query to compute a difference between consecutive documents.
  `$setWindowFields` can do it, but the demo is about the answer, not about undoing
  a modelling mistake.
- **The transformer is denormalised into `meta`.** The balance query groups by
  transformer over hundreds of millions of measurements. Without it in `meta`, that
  becomes a lookup per meter.
- **`expireAfterSeconds` at 400 days** — one full seasonal cycle plus a margin. On a
  time series collection expiry works on the bucket, so a bucket disappears only when
  its newest measurement is past the TTL. That lag is expected, and it is a question
  a customer's DBA will ask.

### Bucketing — measured, not chosen

`granularity` is a shorthand for a bucket span, and the shorthand fits badly here:
15-minute readings under `"minutes"` give a one-hour bucket holding four measurements.
Four variants were loaded with the same 7-day sample and measured;
[`../adr/0001-bucketing.md`](../adr/0001-bucketing.md) has the full table and
`queries/bucket-experiment.json` the raw output.

| Variant | Span | Storage | Index | Ratio¹ | Ingest | Balance 1d |
|---|---|---:|---:|---:|---:|---:|
| plain collection | — | 18.45 MB | 18.74 MB | 1.0× | 33 k/s | 33.2 ms |
| `granularity: "seconds"` | 1 h | 11.46 MB | 8.96 MB | 1.61× | **6.9 k/s** | 32.5 ms |
| `granularity: "minutes"` | 24 h | 4.14 MB | 0.59 MB | 4.46× | 50 k/s | 12.5 ms |
| **`bucketMaxSpanSeconds: 86400`** | 24 h | **2.54 MB** | **0.43 MB** | **7.26×** | 50 k/s | **11.4 ms** |
| `bucketMaxSpanSeconds: 604800` | 7 d | 2.34 MB | 0.37 MB | 7.88× | 43 k/s | 13.0 ms |

¹ storage only. Counting the index, the chosen variant is 12.5× smaller than the same
data in a plain collection.

Two results worth carrying into a customer conversation:

- **The one-hour bucket ingests 7× slower** (6.9 k/s against 50 k/s). The conservative
  default for 15-minute data is the worst option on this table, and nobody guesses that.
- **The explicit pair beats the keyword at the same span** — 7.26× against 4.46×,
  because the server's own rounding packs the buckets less densely.

The parameter cannot be changed after the collection is created. Re-run
`queries/bucket_experiment.py` if the reading interval ever changes.

## Indexes

`schema/indexes.js` is the full idempotent script.

| Collection | Index | Why |
|---|---|---|
| `readings` | `{"meta.meter_id": 1, ts: 1}` | the load curve of one meter |
| `readings` | `{"meta.transformer_id": 1, ts: 1}` | the balance, which is the expensive query |
| `meters` | `{under_investigation: 1}` sparse | the open queue and the deterministic demo reset |
| `meters` | `{meter_id: 1}` unique | point lookup that starts every screen |
| `meters` | `{transformer_id: 1}` | the meters under a transformer |
| `meters` | `{location: "2dsphere"}` | the map panel |
| `transformers` | `{transformer_id: 1}` unique | |
| `investigations` | `{meter_id: 1, status: 1}` | the open queue |
| `investigations` | `{opened_at: -1}` | the alert feed |

An index on a time series collection is an index on the buckets, built from the
control fields the server maintains — which is why `{"meta.x": 1, ts: 1}` is the only
shape worth creating, and why there is no unique index available at all.

### Two deliberate decisions

**No index on `kwh`.** "Every reading above X" over the whole base is not a question
this workload asks, and the index would be as large as the data it indexes.

**No compound `{meta.feeder_id: 1, meta.transformer_id: 1, ts: 1}`.** The feeder
rollup runs from the transformer aggregate, not from raw measurements — one hundred
transformers instead of twenty thousand meters. The index would pay for a query the
model makes unnecessary.

## The five pipelines

Each lives in its own module under `backend/app/db/` and each is returned to the
frontend verbatim behind a `<details>`, so the customer's architect reads exactly what
ran.

1. **Load curve** — `$match` on `meta.meter_id` and a `ts` range, `$group` by
   `$dateTrunc` at the granularity the server chose, `$sort`. This is the one that has
   to be fast in front of an audience.

2. **Gap reconstruction** — the same match, then `$densify` on `ts` with a 15-minute
   step bounded by `partition`, then `$fill` with `locf` on `quality` and `linear` on
   `kwh`, then `$addFields` marking `filled`. The demo meter has a six-hour
   communication outage seeded by the generator.

3. **Transformer balance** — `$group` by `$dateTrunc` hour summing `kwh` across the
   meters under the transformer, `$unionWith` (or a second pass) bringing the boundary
   meter's own reading, `$project` the gap in kWh and in percent, then
   `$setWindowFields` over a trailing window for the moving average and the deviation.
   A gap above `LOSS_THRESHOLD_PCT` for `LOSS_MIN_WINDOWS` consecutive hours is a
   suspicion.

4. **Storage comparison** — `$collStats` with `storageStats` on `readings` and
   `readings_flat`, reported as bytes, documents and the ratio between them. Same
   sample, same day, two collections.

5. **Hot plus cold** — the same load curve against a federated database spanning the
   live collection and the Online Archive, so one query answers across both. Gated by
   `ARCHIVE_ENABLED`.

## The transaction

Opening an investigation writes three things or none:

```
session.start_transaction()
  meters.updateOne({meter_id}, {$set: {under_investigation: true, ...}})
  investigations.insertOne({...evidence, gap_kwh, windows, opened_by})
  meters.updateOne({meter_id}, {$set: {last_event: ...}})   # the change stream trigger
session.commit_transaction()
```

The event is the marking itself, not a synthetic write into a side collection — the
same choice the graph PoV arrived at after the fake-event version failed to convince
anyone. The listener watches `investigations` with a server-side `$match` on the
operation type and coalesces a burst into one alert.

**Nothing is written to `readings` by the backend, ever.** Measurements are facts from
the field; a case is an opinion about them and lives elsewhere. Updates and deletes on
a time series collection are also restricted by design, and a demo that fights that is
a demo arguing with the product.

## Seeds

`data-generator/run_all.sh` runs, in order: assets, readings, comparison sample,
indexes.

Target volume: **20 000 meters × 96 readings/day × 30 days ≈ 57.6 M measurements**,
scaled by `METERS` and `DAYS`. The load curve is synthesised per customer class with a
morning shoulder, an evening peak, a weekend shift and weather noise — a utility
engineer in the room will recognise a fake curve instantly, and the whole demo loses
its footing when they do.

The generator seeds, deterministically: three transformers with non-technical loss at
different intensities, one meter with a six-hour outage, one meter with a voltage
excursion, and one transformer whose gap is entirely technical loss and must **not**
raise a case — the negative control that proves the threshold means something.
