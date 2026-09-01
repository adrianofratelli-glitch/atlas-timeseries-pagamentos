# 03 — Interface and flows

The interface is in **Brazilian Portuguese**: it is presented to Brazilian banks, and
PSP, adquirente, recusa, canal and conta are the words those teams use. The repository
documentation stays in English.

The visual design follows the token set shared across the demonstration projects — dark
background, green for action and success, blue for information, amber for warning, red
for risk. `src/pov-signature.css` carries that signature and is imported after the
application stylesheet. Read `POV_UI_DESIGN_SYSTEM.md` at the workspace root before
touching any of it.

## Stage mode

One screen. The first viewport holds **one thesis** (a provider drifting off its own
baseline), **one action** (pick the provider and the window) and **one piece of
evidence** (the decline curve against its baseline, with the z-score and the measured
response time).

Anything that decides nothing for the presenter is out of the way: the executed pipeline
lives in a `<details>`, and provider, velocity, storage, ranking and incidents sit in the
inspector rail, in script order.

## Layout — one screen, no scrolling

```
┌─ topbar 52px: brand · thesis · eventos · ao vivo · change stream · health ──┐
├──────────┬──────────────────────────────────────────┬─────────────────────┤
│ controls │ metrics: eventos · recusa · z · janelas   │ inspector (tabs)    │
│          │          · resposta · leitura do cursor   │ ┌─────────────────┐ │
│ canal    │ ┌──────────────────────────────────────┐  │ │Prov│Veloc│Armaz│…│ │
│ provedor │ │  uPlot: recusa vs linha de base       │  │ ├─────────────────┤ │
│ janela   │ │  ou p50 / p95 / p99                   │  │ │ detalhe / busca │ │
│ visão    │ │                          [+][−][⤢]   │  │ │ tabelas         │ │
│ ações    │ └──────────────────────────────────────┘  │ └─────────────────┘ │
│ ao vivo  │  ▸ Pipeline executado                     │                     │
│ verdade  │                                           │                     │
├──────────┴──────────────────────────────────────────┴─────────────────────┤
│ alert strip (SSE) · incidentes abertos, mais recente primeiro              │
└───────────────────────────────────────────────────────────────────────────┘
```

`body { overflow: hidden }` and `.app { height: 100dvh }`: the page never scrolls. Only
the control rail and the inspector body scroll internally.

Below 860 px the shell stacks and the document may scroll vertically. The topbar
wraps its status badges onto a second row instead of preserving their desktop
max-content width: that previously widened a 320 px viewport by 498 px and a
768 px viewport by 50 px. The browser surface smoke fixes the contract at
320/768/1600 px and also exercises reload and keyboard focus.

## Charting

`uPlot`, not a React chart library. The series reaches thousands of points and redraws on
every window change; general-purpose libraries build a virtual DOM node per point and
stall well before this volume.

Two things the first version got wrong:

- **The plot is created once and fed with `setData`.** Recreating it whenever the points
  changed destroyed the cursor and any zoom the presenter had set — every 1.5 s while
  live ingestion runs.
- **The callback lives in a ref.** Otherwise a new function identity on each parent
  render rebuilds the chart for no reason.

Three visual rules:

- **The baseline is a dashed grey line under the decline rate.** The story is the gap
  between them, so both have to be on the same axis, and the baseline must not compete
  visually with the measurement.
- **Reconstructed points are dashed and counted.** A reconstructed window never looks
  measured; the metric strip says how many and by which method.
- **The axis says what the server aggregated.** When the window makes the backend switch
  bins, the label says so. Silently changing granularity under a presenter is how a demo
  produces a question nobody can answer on stage.

## The cursor readout

`uPlot`'s own legend sits under the chart. The presenter needs the value where the eyes
already are, so a `setCursor` hook publishes the hovered point and the metric row
replaces "server aggregation" with the instant and the values under the cursor — decline
rate, baseline and z-score in the health view; the three percentiles in the latency view.

## Live ingestion, and the degradation you cause

The play button starts a background feed writing into `payment_events_live`. While it
runs:

- the topbar carries a red *ingerindo ao vivo* badge, and an amber one naming the
  provider being degraded;
- **Injetar degradação** multiplies that provider's decline rate and latency *while the
  feed runs* — the presenter watches the z-score climb, the verdict flip and the
  incident button light up, with nothing pre-recorded;
- the rail shows events written, the simulated clock, the pace and the TTL, with the only
  continuous animation on the screen — a pulsing dot, disabled under
  `prefers-reduced-motion`;
- the chart repaints every 1.5 s **silently**: marking the panel busy on every poll made
  it flicker for the whole demo;
- stopping, or *Reiniciar demo*, clears the collection immediately.

`Reiniciar demo` also reloads health, scenarios and the current chart, and says what it
removed. The first version only called the endpoint, so the screen kept showing the
previous state and the button looked broken.

## The velocity panel

Deliberately not a chart. It is a table of three windows with the query time beside it,
because the claim is about a number and a budget, not about a shape. Planted accounts
appear as chips so the presenter never types an id on stage.

## Streaming

One `EventSource` on `/api/alerts/stream`, opened once at mount and closed on unmount.
The backend `AlertHub` runs the change stream in a thread and fans out to subscribers; a
burst of events from a single transaction is coalesced into one alert. The topbar health
badge shows the stream state — a dead stream must be visible, not silent.

## Screenshots

`docs/screenshots/`, 1600×1000, captured against the real cluster with the scenario
already executed. A latency chart with no data and a health panel with no baseline prove
nothing — run the scenario first, then capture. Alt text names the step it shows.

The data is synthetic and the providers are fictional, so there is no customer identity
to strip. Keep it that way: no real PSP name, no real acquirer code, in the DOM or in the
seeds.
