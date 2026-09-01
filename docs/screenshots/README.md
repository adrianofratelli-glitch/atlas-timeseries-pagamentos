# Screenshots

Empty on purpose. The screenshots that lived here showed the previous vertical (smart
metering) and were removed with the pivot — a screenshot of a screen that no longer
exists is worse than no screenshot.

Capture the new ones against the real cluster, at 1600×1000, **after** running each
scenario, following `../demo-script.md`:

| File | Step |
|---|---|
| `01-armazenamento.png` | storage comparison, time series against a plain collection |
| `02-latencia-percentis.png` | p50/p95/p99 for a channel |
| `03-lacuna-densify-fill.png` | the 40-minute telemetry gap, reconstructed and labelled |
| `04-degradacao-provedor.png` | ADQ-003 drifting off its own baseline |
| `05-controle-negativo.png` | ADQ-006 declining more, and correctly raising nothing |
| `06-velocity-conta.png` | the velocity panel with the measured query time |
| `07-ingestao-ao-vivo.png` | live ingestion with an injected degradation |

A latency chart with no data and a health panel with no baseline prove nothing. Alt text
names the step it shows. The data is synthetic and the providers fictional, so there is
no customer identity to strip — keep it that way.
