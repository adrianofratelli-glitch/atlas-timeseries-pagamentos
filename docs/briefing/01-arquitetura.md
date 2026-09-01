# 01 — Architecture

## Layers

```
┌────────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ React + Vite (5400)    │──▶│ FastAPI (8400)         │──▶│ MongoDB Atlas            │
│ uPlot · p50/p95/p99    │◀──│ app/db  · data access  │◀──│ time series collection   │
│ EventSource (SSE)      │   │ app/services · orch.   │   │ $percentile · $densify   │
│ shared design tokens   │   │ AlertHub · LiveFeed    │   │ $setWindowFields (z)     │
└────────────────────────┘   └────────────────────────┘   │ Change Streams           │
                                                          │ ACID transaction         │
                                                          └──────────────────────────┘
                                                                       ▲
                                                            ┌──────────┴──────────┐
                                                            │ data-generator/     │
                                                            │ idempotente         │
                                                            └─────────────────────┘
```

Layering rule: **no route imports `pymongo`**, and **no module under `app/db/` imports
`fastapi`**. `main.py` exposes HTTP and translates domain errors into status codes;
every query lives in `backend/app/db/`. That symmetry is what lets `queries/bench.py`
reuse the exact production pipelines without installing the web framework.

## Invariants

1. **`meta` carries the route, never the account.** The meta field holds
   `{canal, provedor, produto, uf}` — a few thousand distinct combinations. `conta_id`
   is a **measurement field** with a secondary index. Millions of accounts inside the
   meta field would mean millions of bucket series; `docs/adr/0002-cardinalidade.md`
   measures what that costs instead of asserting it.

2. **Percentiles, not averages.** A payment rail is judged by its tail. Every latency
   answer comes from `$percentile` (p50/p95/p99) computed in the pipeline over raw
   events. An average hides exactly the customer who waited four seconds.

3. **Detection is relative to the provider's own baseline.** `$setWindowFields`
   computes a trailing mean and standard deviation *excluding the window being judged*,
   and the z-score says how far the current window drifted. A credit acquirer that
   declines 23% of transactions is healthy; a PIX PSP that declines 3% is on fire. An
   absolute threshold gets both wrong, and the seeded negative control proves it.

4. **The baseline window ends at −1.** Including the current window in its own baseline
   dilutes the deviation precisely when it matters.

5. **Gap filling happens in the pipeline.** `$densify` creates the missing windows and
   `$fill` carries the last observation forward. The backend never loops over a series
   in Python to patch holes — that is the application-side work a dedicated engine is
   bought to avoid.

6. **A filled point is labelled as filled.** Every reconstructed window carries
   `reconstruido: true` and the method used, the chart draws it dashed, and the metric
   strip counts them. Inventing latency for a payment rail without saying so is how a
   monitoring system loses the trust of the people who operate it.

7. **Ground truth is recorded, never discovered live.** `degradation_scenarios` holds
   the planted degradations — which provider, when, how strong, and whether it *should*
   open an incident. The demo verifies detection against a known answer.

8. **Every window query is bounded in time and in span.** `maxTimeMS`
   (`TS_MAX_TIME_MS`, default 15 s) and a ceiling on the requested range
   (`TS_MAX_RANGE_DAYS`). An unbounded range over tens of millions of events is the
   fastest way to freeze a live demo.

9. **The server decides the granularity.** The client asks for a window in hours; the
   backend picks the `$dateTrunc` bin so the payload stays in the low hundreds of
   points. The chosen granularity is returned and displayed — silently changing it
   under a presenter produces a question nobody can answer on stage.

10. **The velocity query is one pass.** Three windows (1 h, 6 h, 24 h) are three
    `$cond` branches inside one `$group` over the largest window. Three separate queries
    would be three scans and three round trips inside a budget of tens of milliseconds.

11. **Retry only for transient network failure.** `with_retry()` retries
    `AutoReconnect`, `NetworkTimeout` and `ConnectionFailure` with exponential backoff,
    at most 3 times. A logic error is never retried — retrying hides bugs.

12. **Opening an incident is atomic.** Flagging the provider, writing the incident and
    emitting the event happen in one transaction. A provider flagged with no incident
    behind it is an audit finding.

13. **The change stream watches `incidents`, not the events.** Watching
    `payment_events` means one event per transaction — dozens per second, useful for a
    pipeline, useless for driving a screen.

14. **Live ingestion never touches `payment_events`.** The play button feeds
    `payment_events_live`, a separate collection with a one-hour TTL, and its
    measurements carry **real** timestamps. Stamping the simulated clock — which
    continues where the historical base ends, hours in the past — makes the TTL delete
    the live series within a minute.

15. **Concurrency is capped per class of query, and the excess is refused.**
    `app/services/limits.py` gives the analytic path three slots and the interactive
    path twelve; anything that cannot get a slot in 750 ms gets a `429`. Under
    saturation an honest system refuses early instead of taking the interactive path
    down with it.

16. **POST bodies go through a `pydantic` schema, not manual checks.**

## Environment variables

| Variable | Default | Role |
|---|---|---|
| `MONGODB_URI` | — | required |
| `MONGODB_DB` | `trilho_pagamentos` | database |
| `TS_MAX_TIME_MS` | `15000` | ceiling on every aggregation |
| `TS_MAX_RANGE_DAYS` | `30` | ceiling on the requested range |
| `TS_MAX_POINTS` | `4000` | points returned per series |
| `Z_SCORE_THRESHOLD` | `3.0` | deviations from the provider's own baseline |
| `Z_MIN_WINDOWS` | `3` | consecutive anomalous windows before an incident |
| `VELOCITY_WINDOWS` | `1,6,24` | account velocity windows, in hours |
| `DAYS` / `EVENTS_PER_SECOND` / `ACCOUNTS` | `7` / `75` / `2000000` | generator |
| `LIVE_TTL_SECONDS` | `3600` | how long live events survive |
| `LIVE_TICK_SECONDS` | `1.0` | wall-clock seconds per tick |
| `LIVE_MINUTES_PER_TICK` | `30` | simulated minutes per tick |
| `ARCHIVE_ENABLED` | `false` | turns the lifecycle panel on |

`.env.example` is committed; `.env` is not.

## How to run

```bash
python3 -m venv .venv && .venv/bin/pip install -r data-generator/requirements.txt
python3 -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)

bash data-generator/run_all.sh     # registry, events, comparison sample, demo accounts, indexes
./start.sh                         # 8400 + 5400
POV_DEV=1 ./start.sh               # HMR + uvicorn --reload
```

The generator is idempotent through `det_id(kind, *parts)` — a `uuid5` over the key
attributes — everywhere except the events themselves, which live in a time series
collection with no user-controlled `_id` and therefore no upsert. Reloading events
means `--drop`. That asymmetry is a property of the feature, not an oversight.
