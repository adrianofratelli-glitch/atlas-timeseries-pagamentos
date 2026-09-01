# How this project is built

Cover page for the build briefing. The three files in `docs/briefing/` hold
architecture, modelling and interface; this file says what the project proves, what it
does not, and in what order it was built.

## What it demonstrates

That a **payment rail's telemetry does not need a separate stack**. The event, the
provider that routed it, the account that made it, the incident a human opened about it
and the antifraud feature computed from it all live in one Atlas cluster, reached by one
driver, in one query language.

The workload is a digital bank's rail: PIX, card and TED across 44 providers, one
document per authorised transaction.

Six things, one cluster:

1. **Storage**, measured here — the same events in a plain collection and a time series
   collection, `$collStats` side by side.
2. **Latency by percentile** — `$percentile` p50/p95/p99 in the pipeline over raw
   events. A rail is judged by its tail.
3. **The telemetry gap** — a PSP stops reporting for forty minutes; `$densify` and
   `$fill` reconstruct the window inside the pipeline, labelled.
4. **Degradation against the provider's own baseline** — `$setWindowFields` with a
   trailing mean and standard deviation excluding the current window, and a z-score.
5. **Account velocity inside the authorisation** — 1 h / 6 h / 24 h in one pass, with
   the measured latency next to it.
6. **Live ingestion with an injectable degradation** — into a separate collection with a
   one-hour TTL, ending in an ACID incident and a change-stream alert.

## What it does not demonstrate

Ingestion at a bank's real peak, a sharded time series collection, a head-to-head
benchmark against InfluxDB or Prometheus, and cardinality at tens of millions of
accounts. All of it in `LIMITATIONS.md`, which is required reading before presenting.

## Briefing index

| File | Contents |
|---|---|
| [`docs/briefing/01-arquitetura.md`](docs/briefing/01-arquitetura.md) | layers, invariants, environment, how to run |
| [`docs/briefing/02-mongodb.md`](docs/briefing/02-mongodb.md) | collections, indexes, the five pipelines, transaction, seeds |
| [`docs/briefing/03-interface-fluxos.md`](docs/briefing/03-interface-fluxos.md) | frontend, screens, charting, streaming, demo path |

Positioning documents, outside the build briefing:

| File | Contents |
|---|---|
| [`README.md`](README.md) | public cover of the repository |
| [`LIMITATIONS.md`](LIMITATIONS.md) | where the thesis **does not** apply |
| [`queries/benchmarks.md`](queries/benchmarks.md) | numbers measured on this cluster |
| [`docs/demo-script.md`](docs/demo-script.md) | 15-minute script and pre-demo checklist |
| [`docs/business-case.md`](docs/business-case.md) | turning the demo into a number, and what we refuse to estimate |
| [`docs/adr/`](docs/adr/) | recorded architecture decisions |
| [`tests/`](tests/) | hostile suite and mixed-workload stress |

## Order of work

1. **The two experiments before the code.** `bucketMaxSpanSeconds` cannot be changed
   after creation, and the account-in-meta decision changes the whole model. Both were
   measured first — `docs/adr/0001-bucketing.md` and `docs/adr/0002-cardinalidade.md`.
2. **The generator**, because the shape of the traffic decides whether the demo
   survives someone from payments in the room, and because the planted degradations are
   the ground truth the detection is verified against.
3. **Indexes**, including the decisions about which indexes *not* to create.
4. **The comparison collection**, so the storage claim is a fact on screen.
5. **Backend**, data access isolated in `app/db/` and free of `fastapi`.
6. **Frontend**, on the shared visual token set.
7. **Measured benchmarks**, filling `benchmarks.md`.
8. **Trying to break it and to overload it**, before a customer does.

## Why this vertical, and what came before

The first version of this PoV was smart electricity metering — a utility reading meters
every fifteen minutes, detecting non-technical loss. Technically it worked and every
number in it was measured. It was aimed at the wrong audience: presented to a digital
bank, nobody in the room sees themselves in a transformer.

Worse, it left the four objections a bank raises in the first five minutes unanswered,
and said so in writing: cardinality in the millions "is not measured here", detection
used an absolute threshold, latency was reported as an average, and there was no query
in the authorisation path.

The engine survived the pivot — time series collection, measured bucketing, gap
reconstruction, ACID incident, change stream, live ingestion with TTL. The workload,
the detector, the queries and the objections changed. The metering version is preserved
in the `v1-energia` tag.

## What the build corrected

Each of these replaced something that looked right and was not:

- **An absolute decline threshold.** It flagged the healthy acquirer whose product mix
  declines 23% of everything and missed the PSP drifting from 0.3% to 1.2%. The detector
  now compares each provider against its own trailing baseline, and the planted negative
  control exists to keep it honest.
- **A baseline that included the window being judged.** It diluted the deviation exactly
  when the deviation mattered. The window ends at −1.
- **Sorting each batch before inserting.** It bought 12% and looked like the answer.
  Sorting *globally* bought 2×, and the partitioned version that shipped first bought
  nothing at all because each partition still interleaved 81 routes. The unit that has to
  be contiguous is the series.
- **A generator that built one dict per event.** 8.6 k events/s. Sharing the meta
  document per route and vectorising the per-event work took generation to 565 k/s, at
  which point the bottleneck was entirely the server.
- **`insert_many` mutating its input.** It injects `_id` into the caller's dictionaries,
  so reusing a list across two benchmark runs produced duplicate-key errors that looked
  like a concurrency bug.
- **An O(n²) helper in the cardinality experiment.** Picking the busiest account with a
  `max()` over a `sum()` per candidate never finished on 400 000 events.

## State

Built and executed against a real Atlas M20 cluster. The API listens on port 8400 and
the interface on 5400. Database: `trilho_pagamentos`.

**The interface is in Brazilian Portuguese** — it is presented to Brazilian banks, and
PSP, adquirente, recusa and conta are the words those teams use. The repository
documentation is in English; code comments are in Portuguese.
