# Demo script — 15 minutes

Written for a bank. Every step names something the audience owns.

## Pre-demo checklist

Ten minutes before, not while the customer watches.

```bash
curl -s 127.0.0.1:8400/health | jq
```

- `status: ok`, `events` in the tens of millions, `flat_sample: true`
- `change_stream: ativo` — if it says `reconectando`, the live alert will not fire
- `POST /api/demo/reset` — the script opens an incident, and it must not already exist
- Open the interface: **ADQ-003**, 24 h. The verdict must read *degradação*
- Switch to **ADQ-006**: it must read *nada a abrir*, with a higher decline rate

If the detection does not match the ground truth panel, stop. The whole argument rests
on that number being verifiable.

## The line to open with

> "You have a channel, a provider, an account and an incident. Today those live in four
> systems and a feature store. We are going to answer the questions that matter using
> one, and I'm going to show you the numbers rather than a slide."

## 1 · Storage — 2 min

Inspector, **Armazenamento** tab. The same events written twice — a time series
collection and a plain one — with bytes per event side by side and the ratio computed
live.

Say what it is *not*: MongoDB against MongoDB, a fact about the bucket format, not a
claim about InfluxDB. Point at the index column — that is where most of the difference
is, and it is the number the DBA cares about.

Cheapest credibility in the room. That is why it opens.

## 2 · Latency by percentile — 2 min

**Latência**, PIX, 24 h. Three lines: p50, p95, p99.

The sentence: this is `$percentile` over raw events, computed in the database. No
pre-aggregated counter, no second metrics store. Change the window and name what
happened — the server moved the `$dateTrunc` bin; the client asked for a window, not a
granularity.

Hover anywhere: the metric row reads back the instant and all three percentiles.

## 3 · The telemetry gap — 2 min

Still on latency, pick **PSP-021**. There is a 40-minute hole where the provider stopped
reporting. Toggle reconstruction off: a hole. On: the dashed amber segment, labelled,
with the count in the metric strip.

`$densify` created the missing windows and `$fill` carried the last observation forward,
inside the pipeline. No application loop, and every invented point says it was invented.

## 4 · The degradation, and the one that isn't — 4 min

**Recusa**, **ADQ-003**, 24 h. The decline rate lifts off its own baseline; the z-score
crosses three deviations and stays there. The ground-truth panel on the left says what
the seed planted and the screen matches it.

**Now the move that makes the room believe it.** Switch to **ADQ-006**. Its decline rate
is *higher* than ADQ-003's — and the screen says there is nothing to open. That acquirer
declines 23% of everything, all day, by product mix. An absolute threshold flags the
healthy provider and misses the degraded one; comparing each provider against its own
recent history does not.

That is the slide the customer's risk and data teams are waiting for.

## 5 · Velocity inside the authorisation — 3 min

Inspector, **Velocity** tab. Pick the planted account.

Events, amount and decline rate over 1 h, 6 h and 24 h, with the query time next to it.
Say the two things that matter:

- This runs **inside** the decision, not on a dashboard. The budget is tens of
  milliseconds and the number on screen is the measured one.
- It is the same collection, the same cluster. The account is a measurement field with a
  secondary index, not a meta field — `docs/adr/0002-cardinalidade.md` has the measured
  reason, and it is the answer to "won't millions of accounts explode this?".

## 6 · Live, with a degradation you cause — 2 min

**Iniciar ingestão ao vivo**, then **Injetar degradação** on the provider on screen.

Events start landing, the z-score climbs, the verdict flips to *degradação*, and
**Abrir incidente** lights up. One transaction flags the provider, writes the incident
and emits the event; the change stream puts the alert on the strip with nobody
reloading.

Two sentences: the feed writes to `payment_events_live`, a separate collection, so the
historical numbers you verified ten minutes ago are still the same numbers. And it has a
one-hour TTL — nobody cleans up after this demo.

## The close

Count the systems out loud: one cluster, one driver, one query language — for the event,
the route, the incident and the antifraud feature.

Then say the limit before they ask: at their real peak and their real cardinality this
is a sizing exercise on a dedicated cluster, and at the extreme a specialised engine has
a structural advantage. `LIMITATIONS.md` says so in writing, and raising it yourself is
worth more than any number on the screen.

## If something goes wrong

| Symptom | What it is | What to do |
|---|---|---|
| `change_stream: reconectando` | listener lost the cluster | keep going; steps 1–5 do not need it |
| 429 on the health view | analytic queue capped at 3 | wait a second and repeat; say it out loud, refusing early is the design |
| Detection does not match ground truth | wrong or partial data load | stop; do not improvise a number |
| Empty chart | window outside the loaded data | pick 24 h, the anchor is the last event |
| Velocity returns zeros | account outside the 24 h window | use one of the planted chips |
