# 02 — MongoDB

What runs against the cluster. The modelling reasoning — why the account is not in the
meta field, why the event and not a counter — is in
[`schema/collections.md`](../../schema/collections.md).

## Collections

| Collection | Type | Role | Source |
|---|---|---|---|
| `payment_events` | **time series** | one document per authorised transaction | `generate_events.py` |
| `payment_events_flat` | normal | a slice of the same events, for the storage comparison | idem |
| `payment_events_live` | **time series**, TTL 1 h | live ingestion behind the play button | backend |
| `provedores` | normal | PSPs, acquirers and banks, with SLA and baseline decline | `generate_registry.py` |
| `degradation_scenarios` | normal | ground truth of the planted degradations | idem |
| `demo_accounts` | normal | planted velocity profiles, with expected counts | `generate_demo_accounts.py` |
| `incidents` | normal | incidents opened by the ACID transaction | backend |
| `incident_alerts` | normal | change stream fires | backend |
| `dataset_info` | normal | first and last event of each load | `generate_events.py` |

## The event

```js
db.createCollection("payment_events", {
  timeseries: { timeField: "ts", metaField: "meta",
                bucketMaxSpanSeconds: 86400, bucketRoundingSeconds: 86400 }
})
```

```js
{
  ts: ISODate("2026-09-01T14:03:27.412Z"),
  meta: { canal: "pix", provedor: "PSP-014", produto: "pix_chave", uf: "SP" },
  valor: 148.90,
  latencia_ms: 96.4,
  aprovado: true,
  erro: null,
  conta_id: "C001284471"
}
```

`meta` is the **route** — around 2 900 distinct combinations across the three channels.
`conta_id` is a measurement field with a secondary index, not part of `meta`; the
measured reason is in [`../adr/0002-cardinalidade.md`](../adr/0002-cardinalidade.md) and
it is the first objection any bank raises.

## Indexes

`schema/indexes.js` is the full idempotent script.

| Collection | Index | Why |
|---|---|---|
| `payment_events` | `{"meta.provedor": 1, ts: 1}` | provider health, the analytic path |
| `payment_events` | `{"meta.canal": 1, ts: 1}` | channel-wide latency percentiles |
| `payment_events` | `{conta_id: 1, ts: 1}` | account velocity, the authorisation path |
| `provedores` | `{provedor_id: 1}` unique | point lookup behind every screen |
| `provedores` | `{em_incidente: 1}` sparse | open queue and deterministic demo reset |
| `incidents` | `{provedor_id: 1, status: 1}` | the open queue |
| `incidents` | `{opened_at: -1}` | the alert feed |

An index on a time series collection is an index on the buckets. `{conta_id: 1, ts: 1}`
is the interesting one: it indexes a *measurement* field, which is what makes the
high-cardinality dimension queryable without turning it into millions of series.

### Two deliberate decisions

**No index on `valor` or `latencia_ms`.** "Every event above X" is not a question this
workload asks, and the index would approach the size of the data it indexes.

**No `{meta.uf: 1, ts: 1}`.** A cut by state always accompanies a channel or a provider,
both of which already prefix an existing index.

## The five pipelines

Each lives in its own module under `backend/app/db/` and each is returned to the
frontend verbatim behind a `<details>`, so the customer's architect reads exactly what
ran.

1. **Latency by percentile** (`latency.py`) — `$match` on route and range, `$group` by
   `$dateTrunc`, `$percentile` with `p: [0.5, 0.95, 0.99]`. The tail is the product.

2. **Gap reconstruction** (`latency.py`, `fill=true`) — the same pipeline plus
   `$densify` on `ts` with the chosen bin, `$fill` carrying the last observation forward
   for the percentiles and zero for the counts, then a flag marking what was
   reconstructed. The planted PSP stops reporting for 40 minutes.

3. **Provider health** (`providers.py`) — decline rate and p99 per window, then
   `$setWindowFields` computing the trailing mean and standard deviation **excluding the
   current window**, then the z-score. A window is anomalous above
   `Z_SCORE_THRESHOLD` deviations; an incident needs `Z_MIN_WINDOWS` of them in a row.

4. **Account velocity** (`velocity.py`) — one `$match` on `conta_id` over the widest
   window, one `$group` where each narrower window is a `$cond` branch. One pass, one
   round trip, inside the authorisation budget.

5. **Storage comparison** (`storage.py`) — `$collStats` with `storageStats` on the time
   series collection and the plain one, reported per event.

Plus **ranking** (`providers.py`), which is the same percentile aggregation grouped by
provider with a `$lookup` onto the registry for the SLA — the join a metrics stack
cannot do without exporting to a third system.

## The transaction

Opening an incident writes three things or none:

```
session.start_transaction()
  provedores.updateOne({provedor_id}, {$set: {em_incidente: true, ...}})
  incidents.insertOne({...evidencia, z_recusa, z_p99, janelas})
  provedores.updateOne({provedor_id}, {$set: {last_event: ...}})   # gatilho
session.commit_transaction()
```

The event is the flagging itself, not a synthetic write into a side collection. The
listener watches `incidents` with a server-side `$match` and coalesces a burst into one
alert.

**Nothing is written to `payment_events` by the backend, ever.** An event is a fact from
the rail; an incident is an opinion about a window of them.

## Seeds

`data-generator/run_all.sh` runs, in order: registry, events, comparison sample, demo
accounts, indexes.

Volume is set by `DAYS` and `EVENTS_PER_SECOND`. The traffic is synthesised per channel
with the shape a payments engineer recognises — the 4 a.m. trough, the step at 08:00
when commerce opens, the lunch peak, the larger late-afternoon peak, TED dying at 18:00
and nearly absent on weekends, and lognormal latency whose tail is what the p99 sees and
the mean hides.

The generator plants, deterministically:

| Provider | Kind | What it does |
|---|---|---|
| ADQ-003 | `recusa` | decline rate 4× its own baseline for two hours |
| PSP-014 | `latencia` | p99 4.2× for three hours |
| PSP-021 | `apagao` | stops reporting telemetry for 40 minutes |
| **ADQ-006** | `controle` | structurally high decline rate, stable — **must not** open an incident |

The negative control is the point. Its decline rate is *higher* than the degraded
acquirer's peak, so an absolute threshold flags the healthy provider and misses the
broken one. Only a detector comparing each provider against its own recent history gets
both right, and that is why the pipeline is built the way it is.
