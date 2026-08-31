# How this project is built

Cover page for the build briefing. The three files in `docs/briefing/` hold
architecture, modelling and interface; this file says what the project proves, what
it does not, and in what order it is built.

## What it demonstrates

That **a metering workload does not need a time series database beside the
operational one**. The measurement, the asset that produced it, the alert it raised
and the case an analyst opened all live in one Atlas cluster, reached by one driver,
in one query language.

The vertical is a power utility's smart metering (AMI): meters reporting every 15
minutes, a load curve per meter and per transformer, and the question that pays for
the project — **non-technical loss**, the gap between what a transformer delivered
and what the meters under it registered.

Six things, one cluster:

1. **Storage.** The same sample written twice — a plain collection and a time series
   collection — with `collStats` side by side and the compression ratio *measured on
   this cluster*, not quoted from a datasheet.
2. **The window query.** Load curve by hour and by day over tens of millions of
   points, `$dateTrunc` plus an index on the meta field, with `explain` showing what
   the bucket layer skipped.
3. **The gap.** A meter that stopped communicating for six hours. `$densify` and
   `$fill` reconstruct the series in the pipeline — no application loop, no second
   system.
4. **The loss.** Energy balance per transformer: the boundary meter against the sum
   of the meters below it, `$setWindowFields` giving the moving average and the
   deviation, and a sustained gap becoming a suspicion.
5. **The case.** Opening an investigation is one ACID transaction: mark the meter,
   write the case, emit the event. A change stream turns that event into an alert on
   screen.
6. **The lifecycle.** `expireAfterSeconds` on the hot collection, Online Archive for
   the cold one, and one query reading both.

Steps 1 to 5 are the demo. Step 6 is the cost conversation and depends on the
cluster tier — see `LIMITATIONS.md`.

## What it does not demonstrate

Ingestion at millions of points per second, a sharded time series collection, and a
head-to-head benchmark against InfluxDB or TimescaleDB. A dedicated time series
engine tuned for raw write throughput wins that number, and the honest argument here
is a different one: the throughput a distribution utility actually needs is modest,
and what costs it money is operating four systems to answer one question.

There is no Kafka, no AMI head-end protocol and no real meter. The generator writes
straight to the cluster.

All of this is in `LIMITATIONS.md`, which is required reading before any
presentation.

## Briefing index

| File | Contents |
|---|---|
| [`docs/briefing/01-arquitetura.md`](docs/briefing/01-arquitetura.md) | layers, invariants, environment, order of work, how to run |
| [`docs/briefing/02-mongodb.md`](docs/briefing/02-mongodb.md) | collections, bucketing, indexes, the five pipelines, transaction, seeds |
| [`docs/briefing/03-interface-fluxos.md`](docs/briefing/03-interface-fluxos.md) | frontend, screens, charting, streaming, demo path |

Positioning documents, outside the build briefing:

| File | Contents |
|---|---|
| [`README.md`](README.md) | public cover of the repository |
| [`LIMITATIONS.md`](LIMITATIONS.md) | where the thesis **does not** apply |
| [`queries/benchmarks.md`](queries/benchmarks.md) | numbers measured on this cluster, not estimated |
| [`docs/demo-script.md`](docs/demo-script.md) | 15-minute script and pre-demo checklist |
| [`docs/business-case.md`](docs/business-case.md) | turning the demo into a number, and what we refuse to estimate |
| [`docs/adr/`](docs/adr/) | recorded architecture decisions |
| [`tests/`](tests/) | hostile suite and mixed-workload stress |

## Order of work

The order is not arbitrary. Each step exists because the next one cannot be judged
without it.

1. **Bucketing before anything.** `bucketMaxSpanSeconds` decides the storage ratio,
   the query latency and the memory the demo consumes. Choose it, then *measure* it
   against two alternatives before writing a line of backend — see
   `docs/adr/0001-bucketing.md`, which stays open until the measurement lands.
2. **The generator** (`data-generator/`), because the shape of the synthetic data
   decides whether the demo works. Two properties are non-negotiable: a load curve
   that looks like a residential curve to anyone from the sector (morning shoulder,
   evening peak, weekend shift), and ground truth — the meters that are actually
   stealing are recorded, so step 4 is verified rather than hoped for.
3. **Indexes** (`schema/indexes.js`), including the deliberate decisions about which
   indexes *not* to create.
4. **The comparison collection.** A plain `readings_flat` holding one sample of the
   same data, so step 1 of the demo is a fact on screen instead of a claim.
5. **Backend** (`backend/`), data access isolated in `app/db/`.
6. **Frontend** (`frontend/`), on the shared visual token set.
7. **Measured benchmarks** (`queries/bench.py`), filling `benchmarks.md` and the
   tables in `LIMITATIONS.md`.
8. **Trying to break it** (`tests/test_resilience.py`) and to overload it
   (`tests/stress.py`), before a customer does it for us.

## Questions that were open, and how they closed

- **Bucket span** — closed by measurement, `docs/adr/0001-bucketing.md`. Explicit
  `bucketMaxSpanSeconds: 86400`. The surprise was ingestion: the conservative
  one-hour bucket writes **7× slower** (6.9 k/s against 50 k/s), which no one predicted
  from the storage argument alone.
- **Volume** — 58 820 400 measurements loaded at 45 531/s, 464 MB plus 80 MB of index.
  The balance query holds at 337 ms over 30 days on the M20, so the full month stayed
  in the demo.
- **The chart** — `uPlot`. Two adjustments the first version needed: sizing the canvas
  from the container instead of a constant, and reserving the legend's height so it
  does not disappear behind the query drawer.
- **Online Archive** — the demo cluster has no dedicated tier, so step 6 is a
  documented walkthrough and the interface says so instead of faking it.

## What the build corrected

Each of these replaced something that looked right and was not:

- **Ground truth weighted by the wrong thing.** The seeded scenarios were parameterised
  by the *share of meters* defrauded. A commercial customer consumes about five times a
  residential one, so the "severe" scenario measured 16.8% against an expected 27.7%,
  and the negative control ended up with a *larger* gap than a fraud case — no threshold
  separates that. Parameterising by share of **energy**, weighted by the class's average
  weekday factor, brought every scenario within 0.2 pp of its expectation.
- **A day is not a week.** Even with energy weighting, validating on a single day still
  diverged: commercial load falls to 30% on Sunday. The ground truth is a weekly average
  and the seed says so in `expected_basis`.
- **One client per call.** `common.db()` opened a `MongoClient` per invocation, so the
  bucket experiment re-resolved the SRV record on every step and took the local DNS
  down with it.
- **A loading state painted as a failure.** `/health` took 3 s because
  `estimated_document_count()` on 58 M measurements is not free, and for those 3 s the
  interface showed a red "sem conexão" badge with nothing wrong. The count now comes
  from `dataset_info`, and "conectando…" is a state of its own.
- **The data layer importing the web framework.** `ranges.py` raised
  `fastapi.HTTPException`, which meant any script outside the backend virtualenv needed
  the whole framework to compute a date range. It raises a domain error now and
  `main.py` translates.
- **Benchmarking a cluster that was still busy.** The first full-volume run reported a
  281 ms network floor and every query inflated to match, minutes after the bulk load.
  Re-measured on a quiet cluster: 8.5 ms.

## State

Built and executed against a real Atlas M20 cluster. The API listens on port 8400 and
the interface on 5400. Database: `energia_medicao`.

Current state, measured: **58 820 400 measurements** over 30 days, 35 hostile cases
passing, mixed-workload stress with no 5xx up to 64 concurrent clients, and the
transformer balance matching the seeded ground truth to 0.27 pp. Numbers in
`queries/benchmarks.md`.

**The interface is in Brazilian Portuguese** — it is presented to Brazilian
utilities, and medidor, transformador, curva de carga and perda não técnica are the
words those teams use. The repository documentation is in English; code comments are
in Portuguese.
