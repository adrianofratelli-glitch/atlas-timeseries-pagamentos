# Limitations

Where the thesis of this repository does not apply. Read before presenting — the
credibility of the conversation depends on raising these before the customer's
architect does.

## The scope decision

This PoV argues **consolidation**, not throughput. It claims that a distribution
utility's metering workload — tens of thousands of sources, a reading every fifteen
minutes, questions that join the series to the asset and the customer — is answered
well inside the operational database, and that the cost the utility actually carries
is operating four systems rather than saturating any one of them.

It deliberately does not argue that MongoDB out-ingests a dedicated time series
engine. That is a different claim, it is not the customer's bottleneck in this
vertical, and asserting it invites a benchmark this demo would lose.

## What is not demonstrated

**Ingestion at scale.** The generator writes in bulk from one host to seed the base.
There is no sustained-ingest test, no Kafka, no AMI head-end, and no back-pressure
story. A customer asking "can it take two million points a second" is asking a question
this repository does not answer.

**Sharding.** The time series collection is unsharded. Sharding a time series
collection is supported and has real constraints on the shard key, and none of that is
exercised here. Anything said about behaviour beyond a single replica set is opinion.

**A competitive benchmark.** No InfluxDB, no TimescaleDB, no ClickHouse ran beside
this. The storage comparison in step 1 is MongoDB against MongoDB — a time series
collection against a plain one, same data — which is a fact about the bucket format,
not a claim about anyone else's product.

**Real meters.** Fully synthetic data. The load curves are shaped to be recognisable to
someone from the sector, but no real consumption profile, no real distributor, and no
real loss statistic is behind them. The business case in `docs/business-case.md` says
explicitly which numbers it refuses to estimate.

**Cardinality in the millions.** Twenty thousand meters is a mid-size utility feeder
region, not a national IoT platform. Bucket behaviour at millions of distinct meta
values is a different regime and is not measured here.

## Constraints of the feature itself

These are properties of time series collections, not defects of this project, and each
one is a question a DBA in the room will ask:

- **The bucket parameters are fixed at creation.** `bucketMaxSpanSeconds` and
  `bucketRoundingSeconds` cannot be changed later; getting them wrong means recreating
  the collection and rewriting the data. This is why the parameter is measured before
  any code is written.
- **No user-controlled `_id`, therefore no upsert.** Reloading readings means dropping
  and rewriting, and the generator's idempotence does not extend to the measurements.
- **No unique index.** Deduplication has to be handled before the write, not enforced
  by the database.
- **Updates and deletes are restricted.** Correcting historical measurements is not the
  free operation it is on a normal collection, and any design that needs to rewrite the
  past routinely is fighting the storage engine.
- **TTL expires buckets, not documents.** A bucket disappears when its newest
  measurement passes the TTL, so retention is approximate at the bucket boundary.
- **A change stream on the collection fires per measurement.** Useful for a pipeline,
  useless for driving a screen, which is why the live alert in this demo watches
  `investigations` instead.
- **The collection cannot be renamed.** It is a view over `system.buckets.*` and
  `renameCollection` fails with `CommandNotSupportedOnView`. Any workflow that stages
  data under a temporary name and swaps it at the end has to be written differently.
- **The bucket span decides write throughput, not only storage.** Measured here: a
  one-hour span ingests at 6.9 k measurements/s where a one-day span ingests at 50 k/s
  on the same cluster and the same data. A span chosen for storage alone can cost 7× on
  the write path.

## Environment

**Cluster tier.** Built against a shared development Atlas cluster. Online Archive and
Data Federation require a dedicated tier; when the demo cluster does not have one, step
6 is a documented walkthrough and the interface says so instead of faking it.

**Volume ceiling.** Around 57 million measurements at the target settings. Whether the
working set for the transformer balance stays in RAM at that volume is a measurement
recorded in `queries/benchmarks.md`. If it does not, the answer is fewer days on
screen, never a fabricated latency.

**Single region, single replica set.** No multi-region read preference, no failover
timing, no disaster recovery claim.

**A shared cluster.** The demo cluster also hosts other demonstration databases, tens
of gigabytes of them, on 4 GB of RAM and 2 vCPU. Every latency in
`queries/benchmarks.md` was measured under whatever else was resident at the time. That
makes the numbers conservative rather than flattering, and it is worth saying so when
presenting them.

**A network floor of ~8 ms.** Measured from the presenting host to this cluster. Both
curve queries land within a couple of milliseconds of it, so at this volume they
measure the round trip, not the database. Never present them as evidence of query
performance — the balance query and the storage ratio are the numbers that discriminate.

**Concurrency is capped, deliberately.** The balance query has three simultaneous slots
and anything that cannot get one within 750 ms is refused with a 429. Under a synthetic
burst of 24 simultaneous balance requests, 15 were refused. That is the intended
behaviour and not a capacity measurement: it is a demo protecting the interactive path,
not a statement about what the cluster could serve with a queue tuned for throughput.

## What to say when asked

If the question is *raw ingestion rate at millions of sources*, the honest answer is
that a specialised engine has a structural advantage and co-existence is a legitimate
architecture. If the question is *why do I run four systems to bill and audit twenty
thousand meters*, this demonstration is the answer to it.
