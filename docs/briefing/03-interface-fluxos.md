# 03 — Interface and flow

The stage interface has one job: make a live MongoDB time series write and aggregation
impossible to miss.

## One thesis, one action, one evidence chain

There is exactly one visible button: **Iniciar ingestão**, changing to **Parar ingestão**
while the feed runs. No channel, provider, time window, anomaly, incident, ranking or
velocity control belongs to the stage experience.

```text
┌─ MongoDB Time Series ───────────────────────────── Atlas conectado ─┐
│ Veja a série temporal nascer.                  [Iniciar ingestão]   │
│                                                                    │
│ gerador ── { } { } { } ── lote confirmado ──▶ buckets por rota   │
│                                                                    │
│ eventos │ throughput │ confirmação do lote │ agregação no Atlas   │
│ 44,7 M medições → 2,61 M buckets │ 2,26× dados │ 3,73× total     │
│                                                                    │
│ eventos persistidos por segundo ───── curve grows for 60 seconds  │
│ ▸ Ver query / chamada executada                                    │
├──────────────────────────────────────────────────┬─────────────────┤
│                                                  │ bucket físico   │
│                                                  │ latest document │
└──────────────────────────────────────────────────┴─────────────────┘
```

## Motion with operational meaning

The moving BSON packets are the single visual signature. They animate only while the
backend feed is running, and the batch number is published only after `insert_many`
returns. The lane ends in a stack of route buckets rather than a generic database icon;
the highlighted bucket contains the latest confirmed document. With reduced-motion
enabled, the packets remain visible but static.

The chart receives a new one-second aggregation after each serialized poll. Its x-axis
is fixed to 60 seconds from the session start, so the line visibly grows instead of
stretching a handful of points across the entire panel.

## Evidence integrity

`GET /api/live/overview` returns the chart points, query time, a frozen feed state, the
actual collection options and the physical bucket containing that state's latest
document. Collection options are read with `listCollections` and cached for 30 seconds;
the bucket header comes from `system.buckets.payment_events_live` and exposes only
`meta` plus `control.min/max/count/version`. Neither is hard-coded as a successful result.

The aggregation excludes the current, incomplete second. Otherwise the last chart point
looks like a throughput collapse while its batch is still being written.

The compact bucketization strip is deliberately not live telemetry. It is labelled as a
measured benchmark using the same schema and reproduces the versioned historical result:
44,733,964 measurements, 2,613,915 buckets, 17.1 measurements per bucket, 2.26× less
data per event and 3.73× less total storage per event including indexes. Its sources are
`queries/bench-results.json` and `queries/benchmarks.md`.

Starting a new session does not drop data. The API records `started_at`, and the live
aggregation uses the later of that instant or the last 60 seconds. TTL remains the only
retention mechanism.

The technical drawer contains the pipeline that produced the visible curve. It is closed
by default and does not compete with the presentation. When expanded, the main proof
column scrolls internally; the fixed stage shell never clips the pipeline.

## Responsive contract

Desktop uses a large proof stage and a narrow evidence rail. Below 900 px they stack and
the document scrolls vertically. At 360 px the ingestion rail remains horizontal inside
its own contained stage, the metrics form a 2×2 grid, and the single action spans the
width.

Required verification: 360×800, 768×1024 and 1440×1000; no horizontal overflow, visible
keyboard focus, no console errors and a real Play against Atlas.
