# 01 — Architecture

## Layers

```
┌────────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ React + Vite (5400)    │──▶│ FastAPI (8400)         │──▶│ MongoDB Atlas            │
│ uPlot · load curve     │◀──│ app/db  · data access  │◀──│ time series collection   │
│ EventSource (SSE)      │   │ app/services · orch.   │   │ $densify · $fill         │
│ shared design tokens   │   │ AlertHub (thread)      │   │ $setWindowFields         │
└────────────────────────┘   └────────────────────────┘   │ Change Streams           │
                                                          │ ACID transaction         │
                                                          │ Online Archive (opt.)    │
                                                          └──────────────────────────┘
                                                                       ▲
                                                            ┌──────────┴──────────┐
                                                            │ data-generator/     │
                                                            │ idempotent          │
                                                            └─────────────────────┘
```

Layering rule: **no route imports `pymongo`**. `main.py` exposes HTTP and translates
exceptions into status codes; every query lives in `backend/app/db/`. That is what
makes it possible to change driver or server version without touching the routes.

## Invariants

1. **The meta field carries identity, never state.** `meta` holds `meter_id`,
   `transformer_id`, `feeder_id` and `phase` — attributes that do not change over the
   life of the meter. Tariff, contract status and customer class live in `meters` and
   are joined at query time. Writing a mutable attribute into `meta` is the classic
   time series mistake: changing it does not update the past, it starts a new bucket
   series and silently doubles storage.

2. **`bucketMaxSpanSeconds` is a measured decision, not a default.** It is set
   explicitly at collection creation and recorded in `docs/adr/0001-bucketing.md`
   with the numbers behind it. It cannot be changed later without rewriting the
   collection, so it is decided before the generator runs.

3. **Gap filling happens in the pipeline.** `$densify` creates the missing
   timestamps and `$fill` populates them. The backend never loops over a series in
   Python to patch holes — the moment it does, the thesis of this PoV is dead, because
   that is exactly the application-side work a dedicated engine is bought to avoid.

4. **A filled point is labelled as filled.** Every reconstructed measurement carries
   `filled: true` and the method used (`locf` or `linear`). The chart draws it dashed
   and the API returns the count. A demo that quietly invents energy readings for a
   utility is not a demo, it is a liability.

5. **Ground truth is recorded, never discovered live.** `loss_scenarios` holds the
   transformers seeded with non-technical loss, which meters cause it, from when, and
   the expected gap in kWh. The demo never depends on randomness having cooperated,
   and the balance query is verified against a known answer.

6. **Every window query is bounded in time and in span.** `maxTimeMS`
   (`TS_MAX_TIME_MS`, default 15 s) and a cap on the requested range
   (`TS_MAX_RANGE_DAYS`, default 90). An unbounded range over a time series collection
   is the fastest way to freeze a live demo while the server unpacks buckets it will
   throw away.

7. **The server decides the granularity.** The client asks for a range; the backend
   picks `$dateTrunc` at 15 minutes, hour or day from the span, so the payload stays
   in the low thousands of points regardless of what was asked. A browser plotting
   three million points is a browser that has stopped.

8. **Retry only for transient network failure.** `with_retry()` retries
   `AutoReconnect`, `NetworkTimeout` and `ConnectionFailure` with exponential backoff,
   at most 3 times. A logic or validation error is never retried — retrying hides bugs.

9. **Degradation per feature, not per screen.** A missing Online Archive or an
   unavailable federated endpoint becomes a `503` with `{feature, reason}`; the
   frontend badges that panel and every other panel keeps working.

10. **Opening a case is atomic.** Marking the meter, writing the investigation and
    emitting the event happen in one transaction. Half of that state is worse than
    none of it: a meter flagged with no case behind it is an audit finding.

11. **The change stream watches `investigations`, not the measurements.** Watching a
    time series collection to drive a live screen means one event per measurement and
    a flooded UI. The signal a human cares about is the case, and it is emitted once.

12. **POST bodies go through a `pydantic` schema, not manual checks.** Ranges,
    limits and identifiers are validated before they reach a pipeline.

## Environment variables

| Variable | Default | Role |
|---|---|---|
| `MONGODB_URI` | — | required |
| `MONGODB_DB` | `energia_medicao` | database |
| `TS_MAX_TIME_MS` | `15000` | ceiling on every aggregation |
| `TS_MAX_RANGE_DAYS` | `90` | ceiling on the requested range |
| `TS_MAX_POINTS` | `4000` | points returned per series after truncation |
| `LOSS_THRESHOLD_PCT` | `8` | gap that makes a transformer suspicious |
| `LOSS_MIN_WINDOWS` | `6` | consecutive windows above the threshold before a case |
| `ARCHIVE_ENABLED` | `false` | turns the lifecycle panel on |
| `PORT_BACKEND` | `8400` | |
| `PORT_FRONTEND` | `5400` | |

`.env.example` is committed; `.env` is not.

## Order of work

Detailed, with the reason each step precedes the next, in
[`../../implementation_plan.md`](../../implementation_plan.md).

## How to run

```bash
python3 -m venv .venv && .venv/bin/pip install -r data-generator/requirements.txt
python3 -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)

bash data-generator/run_all.sh     # meters, 30 days of readings, comparison sample, indexes
./start.sh                         # 8400 + 5400
POV_DEV=1 ./start.sh               # HMR + uvicorn --reload
```

The generator is idempotent through `det_id(kind, *parts)`, a `uuid5` over the key
attributes — running it twice rewrites the same documents. The exception is the time
series collection itself, which has no user-controlled `_id` and therefore no upsert:
reloading readings means `--drop`. That asymmetry is a property of time series
collections, not an oversight, and it is written down here so nobody "fixes" it.
