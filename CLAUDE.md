# CLAUDE.md

Orientação para o Claude Code neste repositório. Comece por `implementation_plan.md` e
pelo arquivo de `docs/briefing/` que corresponder à tarefa.

## O que é

POV de portfólio (dado 100% sintético, provedores fictícios): telemetria do **trilho de
pagamentos** de um banco digital — PIX, cartão e TED — numa **coleção time series do
MongoDB Atlas**, com a tese de **consolidação**: o evento, o cadastro do provedor, o
incidente e a feature de antifraude no mesmo cluster, em vez de banco de séries +
banco operacional + cache + busca + feature store.

Seis coisas, um cluster:

1. **Armazenamento** — mesma amostra em coleção normal e time series, `$collStats` lado
   a lado, razão medida neste cluster.
2. **Latência por percentil** — `$percentile` p50/p95/p99 no pipeline sobre evento
   bruto. Trilho é julgado pela cauda; média esconde quem esperou quatro segundos.
3. **Lacuna de telemetria** — PSP para de reportar por 40 min, reconstruído com
   `$densify` + `$fill` dentro do pipeline, ponto sempre rotulado.
4. **Degradação contra a própria linha de base** — `$setWindowFields` com média e desvio
   da janela anterior e z-score. O controle negativo (adquirente que recusa 23% de forma
   estável) **não** pode abrir incidente.
5. **Velocity da conta** — 1 h/6 h/24 h numa passada só, dentro do orçamento da
   autorização. `conta_id` é campo de medição indexado, não `metaField` (ADR 0002).
6. **Ao vivo com degradação injetável** — play alimenta `payment_events_live` (TTL 1 h);
   "injetar degradação" faz o z subir, o incidente abrir em transação ACID e o alerta
   chegar por change stream.

**Não** prova ingestão no pico real de um banco, time series shardada, nem benchmark
contra InfluxDB/Prometheus. Ler `LIMITATIONS.md` antes de qualquer apresentação.

Portas: backend **8400**, frontend **5400**. Banco: `trilho_pagamentos`.

A versão anterior desta PoV (vertical energia, medição inteligente) está preservada na
tag `v1-energia`.

## Comandos

```bash
# setup
python3 -m venv .venv && .venv/bin/pip install -r data-generator/requirements.txt
python3 -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)

# dados
bash data-generator/run_all.sh                          # cadastro + eventos + amostra + contas + índices
DAYS=2 EVENTS_PER_SECOND=40 bash data-generator/run_all.sh
.venv/bin/python data-generator/generate_registry.py --drop
.venv/bin/python data-generator/generate_events.py --days 7 --eps 75 --drop   # time series não tem upsert
.venv/bin/python data-generator/generate_events.py --no-sort ...              # reproduz o ADR 0001
.venv/bin/python data-generator/generate_demo_accounts.py --drop
mongosh "$MONGODB_URI" schema/indexes.js

# rodar
./start.sh                    # 8400 + 5400, bundle pronto
POV_DEV=1 ./start.sh          # HMR + uvicorn --reload

# medições
.venv/bin/python queries/bench.py --runs 20             # regrava queries/bench-results.json
.venv/bin/python queries/bucket_experiment.py           # ADR 0001 (span e ordem de escrita)
.venv/bin/python queries/cardinality_experiment.py      # ADR 0002 (conta no meta ou não)
.venv/bin/python tests/test_resilience.py               # suíte hostil
.venv/bin/python tests/stress.py                        # carga misturada

# frontend
(cd frontend && npm run build)
```

## Convenções

- Nenhuma rota importa `pymongo`; nenhum módulo de `app/db/` importa `fastapi`. Erro de
  domínio sobe como exceção própria e `main.py` traduz em status. É o que permite o
  bench reusar os pipelines de produção sem instalar o framework.
- `meta` carrega a **rota** (`canal`, `provedor`, `produto`, `uf`) — milhares de
  combinações. `conta_id` é campo de medição com índice secundário: milhões de contas no
  `metaField` viram milhões de séries. Medido no ADR 0002.
- Percentil, nunca média, para latência. `method: "approximate"` é t-digest e a tela diz
  isso.
- Detecção é desvio da **própria** linha de base do provedor, com a janela terminando em
  `-1`. Incluir a janela atual na base dilui o desvio justamente quando ele importa.
- Ponto preenchido por `$fill` sempre volta marcado e o gráfico desenha tracejado.
- O servidor escolhe a granularidade; o cliente pede janela em horas.
- `maxTimeMS` e teto de faixa em toda agregação.
- O backend nunca escreve em `payment_events`. Evento é fato; incidente é opinião e mora
  em `incidents`.
- Change stream observa `incidents`, não a coleção time series (lá dispara por
  transação).
- Ingestão ao vivo escreve em `payment_events_live` com TTL, carimbada com **tempo
  real** — carimbar o relógio simulado faz a TTL apagar a série em menos de um minuto.
- O gerador agrupa por rota antes de inserir. Ordem de escrita vale 2× em armazenamento
  (ADR 0001) e agrupar por partição não basta: a unidade contígua tem que ser a série.
- O gráfico é criado uma vez e recebe `setData`; recriar a cada poll mata cursor e zoom.
- `/health` lê a contagem de `dataset_info`; `estimated_document_count()` em dezenas de
  milhões custa segundos e é a primeira chamada da tela.
- Bench logo depois de uma carga em massa mede a carga, não o workload. Espere o cluster
  silenciar.
- Interface em pt-BR, documentação do repositório em inglês, comentários de código em
  português.
- Antes de mexer no frontend, ler `POV_UI_DESIGN_SYSTEM.md` na raiz do workspace.
