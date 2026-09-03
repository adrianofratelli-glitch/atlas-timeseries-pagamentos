# How this project is built

Cover page for the build briefing. The three files in `docs/briefing/` hold
architecture, modelling and interface; this file says what the project proves, what it
does not, and in what order it was built.

## What it demonstrates

That **MongoDB Atlas can receive and aggregate a native time series while the audience
watches it being formed**. The stage is intentionally narrower than the engineering
surface: one collection, one Play action and evidence returned by the connected cluster.

The workload is a digital bank's rail: PIX, card and TED across 44 providers, one
document per authorised transaction.

The visible proof has five parts:

1. one mixed `insert_many` feed into `payment_events_live`;
2. confirmed batches and a confirmed document moving on screen;
3. one-second aggregation while writes continue;
4. collection configuration read back from Atlas, plus the executed pipeline on demand.
5. a compact, explicitly historical benchmark strip connecting 44.7 M measurements to
   2.61 M physical buckets and the measured per-event storage reduction.

The historical queries, anomaly detector, incidents, velocity and storage experiments
remain valuable engineering assets. They are no longer navigation choices in the stage
interface because they dilute this proof.

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
- **A detector that failed on both the positive and the negative case.** The baseline
  window ended at −1 and was twelve windows long, so a two-hour degradation walked into
  its own baseline and the z-score collapsed after two windows; meanwhile a very stable
  provider had a standard deviation so small that ordinary noise produced z above 6. It
  now looks back 96 windows, stops four short of the one being judged, and requires the
  deviation to clear both an absolute and a relative floor — the relative one because at
  23.5% decline and ~500 events per window, binomial noise alone is ±1.9 pp.
- **A live view that learned its baseline from a series that only lives an hour.** A
  ten-minute degradation entered the eight-minute baseline and became the reference. The
  live view now compares against the provider's registered baseline, and the screen says
  which reference it used.
- **A channel and a provider that could contradict each other.** The query filtered on
  both, so picking a PIX PSP while the channel said "cartão" returned zero events — and
  `$fill` then cheerfully "reconstructed" the entire empty window. The provider now
  implies the channel, and filling a window with nothing measured in it is refused.
- **A storage panel that hung for 32 seconds.** `$collStats` over 2.6 M buckets is not
  free; it is warmed in a thread at startup and cached.

## State

Built and executed against a real Atlas M20 cluster. The API listens on port 8400 and
the interface on 5400. Database: `trilho_pagamentos`.

**The interface is in Brazilian Portuguese** — it is presented to Brazilian banks, and
PSP, adquirente, recusa and conta are the words those teams use. The repository
documentation is in English; code comments are in Portuguese.
