# MongoDB Atlas time series — live proof

One screen, one action, one claim: MongoDB Atlas can receive and aggregate time series
data while it is arriving.

The workload is a synthetic payment rail. Press **Start ingestion** and one process
writes mixed PIX, card and TED events into `payment_events_live`, a native time series
collection. The interface then shows only evidence returned by the connected cluster:

- the confirmed batch travelling into the collection;
- total events and observed events per second;
- batch confirmation and one-second aggregation latency;
- a throughput curve that grows across a fixed 60-second window;
- the collection's actual `timeField`, `metaField` and TTL configuration;
- the physical bucket containing the latest event, including route, time range,
  measurement count and compression version;
- one document from the latest confirmed batch;
- the aggregation pipeline that produced the chart, closed by default.

There are no channel, provider, anomaly or incident controls in the stage experience.
Those capabilities remain available in the API and engineering material, but they are
not part of this proof.

> Synthetic data and fictional providers. No customer traffic or customer identity.

## What the Play button does

```text
synthetic payment events
          ↓
one mixed insert_many batch
          ↓
payment_events_live (time series + TTL)
          ↓
one-second aggregation returned to the chart
```

Every Play starts a new visual session using `started_at`; it does not delete previous
events. Retention remains the database's job and the TTL expires old buckets.

The default stage rate was validated on the shared M20 at **2 281 confirmed events/s**
for a complete 60-second window while the chart aggregation ran concurrently. The UI
shows the rate actually acknowledged by Atlas, not the generator's nominal input. This
is a presentation operating point, not a production sizing claim.

## What this proves

- a native MongoDB time series collection accepts the live workload;
- one batch can contain multiple event routes — channel is data, not an ingestion
  pipeline;
- the same collection can be aggregated while writes continue;
- the configuration and sample shown on screen belong to the live collection.

## What this does not prove

This is not a production capacity test, a sizing result, a sharding exercise or a
competitive benchmark against a specialised time series engine. See
[`LIMITATIONS.md`](LIMITATIONS.md) before presenting it to a customer.

## Setup

```bash
cp .env.example .env
python3 -m venv .venv && .venv/bin/pip install -r data-generator/requirements.txt
python3 -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)

bash data-generator/run_all.sh
./start.sh                  # API 8400, interface 5400
```

## Verification

```bash
python3 -m compileall -q backend tests
(cd frontend && npm run build)
.venv/bin/python tests/test_resilience.py
node ../pov-portfolio/tests/browser_surface_smoke.mjs timeseries=http://127.0.0.1:5400
```

The broader experiments and measured results remain in [`queries/`](queries/) and
[`docs/adr/`](docs/adr/). The previous electricity-metering version is preserved in
the `v1-energia` tag.
