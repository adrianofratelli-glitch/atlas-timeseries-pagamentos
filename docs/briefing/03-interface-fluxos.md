# 03 — Interface and flows

The interface is in **Brazilian Portuguese**: it is presented to Brazilian
utilities, and medidor, transformador, curva de carga, alimentador and perda não
técnica are the words those teams use. The repository documentation stays in English.

The visual design follows the token set shared across the demonstration projects —
dark background, green for action and success, blue for information, amber for
warning, red for risk. `src/pov-signature.css` carries that signature and is imported
after the application stylesheet. Read `POV_UI_DESIGN_SYSTEM.md` at the workspace root
before touching any of it.

## Stage mode

One screen. The first viewport holds **one thesis** (a transformer losing energy),
**one action** (pick the transformer and the range) and **one piece of evidence** (the
two curves diverging, with the gap in kWh and the measured response time).

Anything that decides nothing for the presenter is out of the way: the executed
pipeline lives in a `<details>`, and storage, gap filling and lifecycle sit in the
panel rail beside the chart, in script order.

## Layout — one screen, no scrolling

```
┌─ topbar 52px: brand · one-line thesis · health ───────────────────────────┐
├──────────┬──────────────────────────────────────────┬─────────────────────┤
│ controls │ metrics: meters · points · gap kWh ·      │ inspector (tabs)    │
│          │          gap % · query ms · filled pts    │ ┌─────────────────┐ │
│ meter /  │ ┌──────────────────────────────────────┐  │ │Ativo│Armaz.│Ciclo│ │
│ transf.  │ │  uPlot: delivered vs registered      │  │ ├─────────────────┤ │
│ range    │ │  band = gap · dashed = filled        │  │ │ meter detail    │ │
│ granul.  │ │                          [+][−][⤢]   │  │ │ storage ratio   │ │
│ action   │ └──────────────────────────────────────┘  │ │ archive state   │ │
│          │  ▸ Pipeline executado                     │ └─────────────────┘ │
├──────────┴──────────────────────────────────────────┴─────────────────────┤
│ alert strip (SSE) · cases opened, newest first                            │
└───────────────────────────────────────────────────────────────────────────┘
```

`body { overflow: hidden }` and `.app { height: 100dvh }`: the page never scrolls.
Only the control rail and the inspector body scroll internally, when they need to.

## Charting

`uPlot`, not a React chart library. The series is thousands of points and redraws on
every range change; the general-purpose libraries build a virtual DOM node per point
and stall well before the volume this PoV puts on screen. The wrapper is a small
component owning a `ref` and an effect — React never re-renders the canvas, it only
hands over new data.

Three visual rules the chart must obey:

- **Filled points are dashed and counted.** A reconstructed reading never looks like a
  measured one. The metric strip shows how many were filled and by which method.
- **The gap is a band, not a third line.** Delivered and registered are two lines; the
  area between them is the number the customer cares about, so it is the shape the eye
  lands on.
- **The axis says what the server aggregated.** When the range makes the backend
  switch from 15 minutes to hour to day, the label says so. Silently changing
  granularity under a presenter is how a demo produces a question nobody can answer on
  stage.

## The cursor readout

`uPlot`'s own legend sits under the chart. The presenter needs the value where the eyes
already are, so a `setCursor` hook publishes the hovered point and the metric row
replaces "server aggregation" with the instant, the two values and the gap under the
cursor. Moving off the chart restores the label.

Two consequences the first version got wrong:

- **The plot is created once and fed with `setData`.** Recreating it whenever the points
  changed destroyed the cursor and any zoom the presenter had set — every 1.5 s while
  live ingestion runs.
- **The callback lives in a ref.** Otherwise a new function identity on each parent
  render rebuilds the chart for no reason.

## Live ingestion

The play button starts a background feed writing into `readings_live`. While it runs:

- the topbar carries a red *ingerindo ao vivo* badge;
- the rail shows measurements written, the simulated clock, the pace and the TTL, with
  the only continuous animation on the screen — a pulsing dot, disabled under
  `prefers-reduced-motion`;
- the chart repaints every 1.5 s **silently**: marking the panel busy on every poll made
  it flicker for the whole demo;
- stopping, or *Reiniciar demo*, clears the collection immediately.

`Reiniciar demo` also reloads health, scenarios and the current chart, and says what it
removed. The first version only called the endpoint, so the screen kept showing the
previous state and the button looked broken.

## Streaming

One `EventSource` on `/api/alerts/stream`, opened once at mount and closed on unmount.
The backend `AlertHub` runs the change stream in a thread and fans out to subscribers;
a burst of events from a single transaction is coalesced into one alert. Reconnection
is the browser's default with a server-sent `retry`, and the topbar health badge shows
the stream state — a dead stream must be visible, not silent.

## Demo path — 15 minutes

The full script with timings and the pre-demo checklist is in
[`../demo-script.md`](../demo-script.md). The shape:

1. **Storage, 2 min.** The Armazenamento tab: same day, same readings, two
   collections, the ratio measured live. This is the cheapest credibility in the whole
   deck and it opens the demo for that reason.
2. **The curve, 2 min.** One meter, thirty days, the response time next to it. Change
   the range and watch the server change granularity.
3. **The gap, 2 min.** The meter with the six-hour outage. Filling off: a hole.
   Filling on: dashed points, labelled, reconstructed in the pipeline — no application
   code.
4. **The loss, 4 min.** Switch to the transformer. Two curves, the band between them,
   the moving average crossing the threshold for six consecutive hours. Then the
   negative control: the transformer whose gap is technical loss and raises nothing.
5. **The case, 3 min.** Open the investigation. One transaction, three writes, and the
   alert arriving on the strip through the change stream while nobody reloaded
   anything.
6. **The lifecycle, 2 min.** Hot collection with its TTL, cold data in the archive, one
   query across both — or, if the tier does not allow it, the walkthrough and an honest
   sentence saying it is not running here.

The close is the count of systems: one cluster, one driver, one query language, for
the series, the asset, the alert and the case.

## Screenshots

`docs/screenshots/`, 1600×1000, captured against the real cluster with the scenario
already executed. A load curve with no data and a balance panel with a zero gap prove
nothing — run step 4 first, then capture. Alt text names the step it shows.

The data is synthetic and the utility is fictional, so there is no client identity to
strip. Keep it that way: no real distributor name, no real feeder code, in the DOM or
in the seeds.
