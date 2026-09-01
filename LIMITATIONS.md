# Limitations

Where the thesis of this repository does not apply. Read before presenting — the
credibility of the conversation depends on raising these before the customer's
architect does.

## The scope decision

This PoV argues **consolidation**, not throughput. It claims that a payment rail's
telemetry — a few thousand routes, tens of millions of events, questions that join the
event to the provider, the account and the incident — is answered well inside the
operational database, and that what the bank actually pays for today is operating five
systems rather than saturating any one of them.

It deliberately does not argue that MongoDB out-ingests a dedicated time series engine.
That is a different claim, it is not the bottleneck in this workload, and asserting it
invites a benchmark this demo would lose.

## What is not demonstrated

**Ingestion at a bank's real peak.** The generator loads in bulk from one host and the
measured ceiling on this cluster is in `queries/benchmarks.md`. There is no Kafka, no
back-pressure story, and no sustained-ingest test at production rates. A bank asking
"can it take our peak PIX second" is asking a question this repository does not answer —
the honest response is a sizing exercise on a dedicated cluster, not this demo.

**Sharding.** The collection is unsharded. Sharding a time series collection is
supported and has real constraints on the shard key, and none of that is exercised here.
Anything said about behaviour beyond a single replica set is opinion.

**A competitive benchmark.** No InfluxDB, no TimescaleDB, no ClickHouse, no Prometheus
ran beside this. The storage comparison is MongoDB against MongoDB — a time series
collection against a plain one, same events — which is a fact about the bucket format,
not a claim about anyone else's product.

**Cardinality at a real bank's account count.** Two million accounts here. A large
retail bank has tens of millions. `docs/adr/0002-cardinalidade.md` measures the *shape*
of the problem — what happens when the account enters the meta field versus staying a
measurement field — at this scale. The direction of the result is structural and does
not reverse with more accounts; the magnitudes would need re-measuring.

**Real traffic.** Fully synthetic data, fictional providers. The volume curves are
shaped to be recognisable to someone from payments — the 4 a.m. trough, the lunch peak,
TED dying at 18:00, lognormal latency with a real tail — but no customer's traffic, no
customer's decline rates and no customer's incident history is behind them.

**Retention at regulatory horizon.** BACEN-scale retention is years. This dataset holds
days. `expireAfterSeconds` and Online Archive are demonstrated as mechanisms; the cost
model at multi-year retention is a sizing conversation, not a measurement here.

**Multi-region and failover.** Single region, single replica set. No read preference
story, no failover timing, no DR claim.

## Constraints of the feature itself

Properties of time series collections, not defects of this project, and each one is a
question a DBA in the room will ask:

- **The bucket parameters are fixed at creation.** `bucketMaxSpanSeconds` and
  `bucketRoundingSeconds` cannot be changed later; getting them wrong means recreating
  the collection and rewriting the data. Measured before any code was written —
  `docs/adr/0001-bucketing.md`.
- **The bucket span is a ceiling, not a promise.** A bucket also closes on a measurement
  count and a size limit, so at high event density per route the span stops being the
  binding constraint.
- **No user-controlled `_id`, therefore no upsert.** Reloading events means dropping and
  rewriting.
- **No unique index.** Deduplication has to happen before the write.
- **Updates and deletes are restricted.** Correcting history is not free, and any design
  that needs to rewrite the past routinely is fighting the storage engine.
- **TTL expires buckets, not documents.** Retention is approximate at the bucket
  boundary.
- **The collection cannot be renamed** — it is a view over `system.buckets.*`.
- **A change stream on the collection fires per event.** Useful for a pipeline, useless
  for driving a screen, which is why the live alert watches `incidents`.
- **`$percentile` with `method: "approximate"`** is a t-digest estimate. It is the mode
  supported over a stream of this size, and the approximation is irrelevant for deciding
  whether a provider degraded — but it is an estimate, and saying otherwise to a risk
  team is how credibility ends.

## Environment

**A shared development cluster.** M20, 4 GB RAM, 2 vCPU, hosting other demonstration
databases at the same time. Every number in `queries/benchmarks.md` was measured under
whatever else was resident. That makes them conservative rather than flattering.

**A network floor of ~8 ms** from the presenting host to this cluster. Any query
reported near that number is measuring the round trip, not the database.

**The live ingestion is a demonstration device.** A single background thread inside the
API writing a few hundred events per tick from the same synthetic model. It exists so
the audience can watch events arrive, a provider degrade, an incident open and the data
expire — not to characterise ingestion capacity.

**Concurrency is capped, deliberately.** The analytic path has three simultaneous slots
and refuses the excess with a `429` after 750 ms. That is a demo protecting the
interactive path, not a statement about what the cluster could serve with a queue tuned
for throughput.

## What to say when asked

If the question is *raw ingestion at our peak with our cardinality*, the honest answer
is that it is a sizing exercise on a dedicated cluster and that a specialised engine has
a structural advantage at the extreme — co-existence is a legitimate architecture.

If the question is *why do we run five systems to know that an acquirer is degrading and
to score an account's velocity*, this demonstration is the answer to it.
