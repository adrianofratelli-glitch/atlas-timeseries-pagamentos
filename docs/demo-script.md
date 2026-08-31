# Demo script — 15 minutes

## Pre-demo checklist

Ten minutes before, not while the customer watches.

```bash
curl -s 127.0.0.1:8400/health | jq
```

- `status: ok`, `readings` in the tens of millions, `flat_sample: true`
- `change_stream: ativo` — if it says `reconectando`, the live alert will not fire
- `POST /api/demo/reset` — the script opens a case, and it must not already exist
- Open the interface, pick **TR-00000**, 7 days: the gap must read ~28%
- Switch to **TR-00003**: it must read ~7% and say there is nothing to investigate

If the balance does not match the ground truth panel, stop. Something is loaded wrong,
and the whole argument of the demo rests on that number being verifiable.

## The line to open with

> "This utility reads twenty thousand meters every fifteen minutes. The usual
> architecture for that is four systems. We are going to answer the question that pays
> for the project using one."

## 1 · Storage — 2 min

Inspector, **Armazenamento** tab.

The same measurements, written twice: a time series collection and a plain one. Read
the bytes-per-measurement column out loud, then the ratio.

Say what it is *not*: this is MongoDB against MongoDB, not against InfluxDB. It is a
fact about the bucket format. Point at the index column — that is where most of the
difference comes from, and it is the number a DBA will care about.

Open this way because it is the cheapest credibility in the whole conversation.

## 2 · The load curve — 2 min

**Curva**, one meter, 1 day. Point at the evening peak and the weekend shift when you
move to 30 days.

Change the range and name what happened: the server moved from 15 minutes to hour to
day. The client asked for a range, not a granularity. Show the response time.

Open the query drawer once, here, and leave it closed for the rest of the demo.

## 3 · The gap — 2 min

Same screen, the meter marked **falha de comunicação**. Toggle *Reconstruir lacuna*
off: a hole. On: the dashed amber segment appears, and the metric strip says how many
points were reconstructed and by which method.

The sentence that matters: `$densify` and `$fill` did that inside the pipeline. No
application loop, no second system, and every invented point is labelled as invented —
which is the only acceptable way to show a utility a reading that did not happen.

## 4 · Non-technical loss — 4 min

**Balanço**, TR-00000, 7 days.

Two lines: delivered by the transformer, registered by the meters below it. The red
band between them is energy nobody billed. The moving average from
`$setWindowFields` crosses the threshold and stays there.

Then the move that makes the room believe it: the ground truth panel on the left says
what the seed planted, and the measured gap matches it. The demo is checked against a
known answer, not against luck.

**Now the negative control.** Switch to TR-00003. Gap of ~7%, and the screen says
there is nothing to investigate — that transformer is old and its loss is entirely
technical. A detector that flags everything is not a detector, and this is the slide
the customer's data team is waiting for.

## 5 · The case — 3 min

**Abrir investigação.**

One transaction: the meter is flagged, the case is written, the event is emitted. All
three or none — a flagged meter with no case behind it is an audit finding.

The alert appears at the bottom without anybody reloading. That is a change stream on
`investigations`. Say why it is not on the measurements: there it would fire once per
reading and flood the screen.

## 6 · The lifecycle — 2 min

`expireAfterSeconds` on the hot collection, Online Archive for the cold years, one
query across both.

If the demo cluster has no dedicated tier, say so plainly and walk through it instead
of faking it. The interface badges the panel as unavailable for exactly this reason.

## The close

Count the systems out loud: one cluster, one driver, one query language — for the
series, the asset, the alert and the case.

Then say the limit before they ask it: at millions of points per second from millions
of devices, a specialised engine has a structural advantage and co-existence is a
legitimate architecture. That is in `LIMITATIONS.md`, and raising it yourself is worth
more than any number on the screen.

## If something goes wrong

| Symptom | What it is | What to do |
|---|---|---|
| `change_stream: reconectando` | listener lost the cluster | keep going; steps 1–4 do not need it, come back to 5 |
| 429 on the balance | the analytic queue is capped at 3 | wait a second and repeat; say it out loud, refusing early is the design |
| Balance does not match the ground truth | wrong or partial data load | stop the demo; do not improvise a number |
| Empty chart | requested range outside the loaded data | pick 7 days, the anchor is the last measurement |
