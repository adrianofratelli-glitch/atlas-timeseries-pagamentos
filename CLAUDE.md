# CLAUDE.md

Orientação para o Claude Code neste repositório. Comece por `implementation_plan.md` e
pelo arquivo de `docs/briefing/` que corresponder à tarefa.

## O que é

POV de portfólio com dado 100% sintético: uma prova visual e verificável de que o
**MongoDB Atlas recebe e agrega uma série temporal enquanto ela nasce**.

Uma tela, uma ação, uma tese:

1. **Play** inicia um único processo que grava PIX, cartão e TED misturados em lotes na
   coleção time series `payment_events_live`.
2. **Fluxo vivo** mostra apenas lotes já confirmados pelo `insert_many`; o último
   documento exibido pertence ao mesmo lote.
3. **Consulta simultânea** agrega eventos por segundo enquanto as escritas continuam e
   desenha uma janela fixa de 60 s.
4. **Prova técnica** lê do Atlas `timeField`, `metaField`, TTL e o bucket físico do
   último evento (`control.min/max/count/version`), além de oferecer o pipeline
   executado sob demanda.
5. **Resultado da bucketização** separa a execução ao vivo do benchmark histórico com
   o mesmo schema: 44,7 M medições em 2,61 M buckets, 2,26× menos dados por evento e
   3,73× menos armazenamento total por evento incluindo índices.

Provedores, detecção, incidentes, velocity, ranking e comparação de armazenamento
continuam no backend e no material de engenharia, mas não pertencem ao modo palco.

**Não** prova ingestão no pico real de um banco, sizing, time series shardada nem
benchmark contra InfluxDB/Prometheus. Ler `LIMITATIONS.md` antes de apresentar.

Portas: backend **8400**, frontend **5400**. Banco: `trilho_pagamentos`.

A versão anterior desta PoV (vertical energia, medição inteligente) está preservada na
tag `v1-energia`.

## Como subir

Pelo portal do portfólio (`povs` no terminal, depois o botão da PoV). O
`start.sh` é o launcher que ele executa e cumpre o contrato do orquestrador:

- fica em **primeiro plano**, para o grupo de processos segurar os filhos;
- derruba a **árvore inteira** no SIGTERM — `npm run preview` gera um neto (vite)
  que continua escutando a 5400 se só o npm morrer;
- arma o trap **antes** de subir qualquer coisa, para um encerramento durante a
  partida não deixar órfão;
- **espera até 10 s** por uma porta que ainda está fechando de uma ativação
  anterior, em vez de falhar de imediato — o ciclo normal do portal é encerrar e
  reativar em seguida;
- os dois serviços rodam com `cwd` dentro do repositório, que é como o
  orquestrador identifica o que é dele para encerrar.

Este é o motivo de a PoV **não** ficar com `availability: in_progress` no
`povs.json`: o orquestrador recusa ativar uma PoV nesse estado.

Rodar à mão (`./start.sh`) funciona, mas fora do portal o controller pode
encerrar os processos ao ativar outra PoV — a política é `single-active` e ela é
aplicada por `cwd`.

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
- Há **um** processo de ingestão ao vivo para o trilho completo. PIX, cartão e TED
  entram no mesmo lote; canal é dimensão do evento e filtro de análise, nunca um
  seletor de pipeline.
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

## Correções de auditoria (2026-09)

- `RANKING_MAX_HOURS` era usada em `providers.ranking()` sem estar definida em
  `config.py` — `NameError` em `/api/ranking`. Constante adicionada.
- Modo ao vivo não calcula z-score de verdade (série curta demais para aprender a
  própria base). O campo agora se chama `delta_ratio_recusa`/`delta_ratio_recusa_max`
  (era `z_recusa`/`z_recusa_max`, nome enganoso); `z_p99` ao vivo virou
  `p99_score_indisponivel`. Frontend e payload de abertura de incidente ajustados.
- `incidents.abrir()` tinha race condition: a checagem `em_incidente` era só fast-path,
  e sem olhar `modified_count` do `update_one` dentro da transação, uma corrida
  concorrente podia gerar dois incidentes "abertos" para o mesmo provedor.
- Ingestão ao vivo (`live.py`) agora escreve com `with_retry()` em vez de
  `insert_many` direto, para sobreviver a falha transitória de rede; estado da thread
  passou a distinguir `parado` de `erro`.
- `AlertHub._seen` (change stream de incidentes) agora poda entradas antigas — antes
  crescia sem limite pela vida do processo.
