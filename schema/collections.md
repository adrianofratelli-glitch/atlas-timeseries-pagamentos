# Modelling

Why the documents look the way they do. The operational detail — indexes, pipelines,
seeds — is in [`../docs/briefing/02-mongodb.md`](../docs/briefing/02-mongodb.md).

## The split: measurement, asset, opinion

Three kinds of document, three collections, on purpose.

**The measurement** (`readings`, time series) is a fact from the field. It is written
once, never updated, and the backend never writes to it at all. Time series
collections restrict updates and deletes precisely because that is the contract, and a
design that needs to rewrite the past routinely is arguing with the storage engine.

**The asset** (`meters`, `transformers`, `feeders`) is state. It changes: a meter is
flagged, a customer changes tariff, a transformer is replaced. It is a normal
collection with unique indexes, upserts and everything a registry needs.

**The opinion** (`investigations`, `loss_alerts`) is what a human concluded from the
other two. Separate because it has a different lifecycle, a different retention and a
different audience — and because the change stream that drives the live screen has to
watch something that fires once per case, not once per measurement.

## What goes in `meta`, and what does not

```js
meta: { meter_id, transformer_id, feeder_id, phase, kind }
```

The rule: `meta` carries **identity**, never state.

A meta field is part of the bucket's identity. Change it and the server does not
update history — it starts a new bucket series for the new value, and the same meter
now has its measurements split across two lineages. Storage grows, and a query
filtering on the old value silently stops seeing the new data.

So `tariff`, `customer_class` and `under_investigation` live in `meters` and are joined
at query time. They are all mutable, and all three were candidates for `meta` on the
first pass because they read like "attributes of the meter".

`transformer_id` is denormalised into `meta` even though it is technically derivable
from `meters`. The balance query groups by transformer across the whole collection;
without it in `meta`, that is a lookup per meter. It is also genuinely immutable in
this model — a meter moving to another transformer is a new install.

`kind` (`medidor` / `fronteira`) is what lets one collection hold both sides of the
balance. The boundary meter is not a special table: it is a measurement with a
different `kind`, which is why the balance is one `$group` and not a join.

## The measurement is the interval, not the register

`kwh` is the consumption of that 15-minute interval. A real meter reports a cumulative
register, and storing that would force every query to difference consecutive
documents. `$setWindowFields` can do it, but then every question about energy is
preceded by undoing a modelling choice.

The trade-off is honest and worth saying out loud to a customer: interval storage
loses the ability to detect a register rollback or a tamper that resets the meter. In a
real deployment you store both — the register for audit, the interval for analytics.
This PoV stores the interval because that is what the demonstration asks about.

## Registered versus delivered

The meter records what it **registered**; the boundary meter records what was
**delivered**. Non-technical loss is the difference the meter never saw, so it cannot
be a field on the meter's own document — it only exists as a relationship between two
series.

That is why the generator holds `register_factor` on `meters` (ground truth, kept out
of the API's meter projection) and why the demo's claim is always about a transformer,
never about a single meter until a human opens a case.

## Bucketing

`bucketMaxSpanSeconds: 86400`, decided by measurement in
[`../docs/adr/0001-bucketing.md`](../docs/adr/0001-bucketing.md) and not by preference.
Fixed at creation; changing it means recreating the collection.

## Two constraints that shaped the code

**No user-controlled `_id`, so no upsert.** The generator is idempotent everywhere
except the measurements, where reloading means `--drop`. Do not "fix" that.

**A time series collection cannot be renamed.** It is a view over `system.buckets.*`,
and `renameCollection` fails with `CommandNotSupportedOnView`. Any script that stages
data under a temporary name and swaps it at the end has to be written differently here.
