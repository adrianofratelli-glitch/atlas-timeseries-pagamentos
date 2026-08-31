# Business case

How to turn the demonstration into a number, and which numbers this repository
refuses to produce.

## What the demo measures, and what it does not

The demo measures **energy that was delivered and never registered** for one
transformer over a chosen window: `gap_kwh`. That number is real in the sense that it
comes from the data on screen.

It is *not* recovered revenue. Between the gap and the money there are three steps the
demonstration cannot take:

1. **Part of the gap is technical loss.** Heating in the transformer and the secondary
   network is physics, not theft, and it is not recoverable. The screen shows that
   directly: the negative-control transformer has a 7% gap and nothing to investigate.
2. **A suspicion is not a confirmation.** A field inspection confirms some fraction of
   the cases. That fraction is the utility's, from its own history, and it varies by
   region by a factor of two or more.
3. **Confirmation is not collection.** Recovering billed-in-arrears energy is a legal
   and commercial process with its own success rate.

Any slide multiplying `gap_kwh` by a tariff and calling it savings is doing all three
steps silently. Do not build that slide.

## The number this repository will produce

```
energia_nao_registrada_kwh  — measured, on screen
tarifa                      — the customer's, per class
custo_inspecao              — the customer's
```

`estimativa.valor` in a case is `gap_kwh × tariff`, and both the API payload and the
interface label it as an estimate whose basis was **informed by the customer**, not
measured. `KWH_TARIFF` and `FIELD_INSPECTION_COST` live in `.env` next to a comment
saying they are not measurements.

## The argument that does not need those numbers

The consolidation case stands on operations, and it is the one this PoV actually
proves:

- **Systems removed.** The reference architecture for this workload is a time series
  database, a relational database for the registry, a cache for the dashboard and a
  search engine for case history. This runs on one cluster. Four sets of credentials,
  backups, upgrades, on-call rotations and integration tests become one.
- **Joins that stop being pipelines.** "The load curve of every commercial meter under
  transformers installed before 2010" is one aggregation here. Across two systems it is
  a synchronisation job, and synchronisation jobs are where the data drifts.
- **Storage, measured.** `queries/benchmarks.md` has the bytes-per-measurement and the
  ratio against a plain collection, measured on this cluster. That number translates
  directly into a disk line on an invoice, and it does not require anyone to believe
  an estimate.

## What to ask the customer for

If they want a business case with their own numbers, these are the four inputs, and
none of them can be invented on our side:

1. Meters in the region, and the reading interval.
2. Current non-technical loss rate, and how it is measured today.
3. Field inspection cost, and the confirmation rate of current inspections.
4. The list of systems in the current metering architecture, with their licence and
   operating costs.

With those, the model is arithmetic. Without them, the honest deliverable is the
demonstration and the measured storage ratio — which is already more than most
proposals put on the table.
