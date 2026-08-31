# CLAUDE.md

Orientação para o Claude Code neste repositório. Comece por
`implementation_plan.md` e pelo arquivo de `docs/briefing/` que corresponder à
tarefa.

## O que é

POV de portfólio (dado 100% sintético, distribuidora fictícia): medição inteligente
de energia (AMI) numa **coleção time series do MongoDB Atlas**, com a tese de
**consolidação** — a série, o cadastro do ativo, o alerta e o caso de investigação
vivem no mesmo cluster, alcançados por um driver só, em vez de InfluxDB/Timescale ao
lado do banco operacional mais Redis mais Elastic.

Seis coisas, um cluster:

1. **Armazenamento** — mesma amostra em coleção normal e time series, `$collStats`
   lado a lado, taxa de compressão medida neste cluster.
2. **Curva de carga** — janela por 15 min / hora / dia com `$dateTrunc` sobre dezenas
   de milhões de pontos.
3. **Lacuna** — medidor sem comunicação por 6 h reconstruído com `$densify` + `$fill`
   dentro do pipeline, nunca em laço na aplicação.
4. **Perda não técnica** — balanço energético do transformador (medidor de fronteira
   × soma dos medidores abaixo) com `$setWindowFields` para média móvel e desvio.
5. **Caso** — abrir investigação é uma transação ACID; o change stream vira alerta na
   tela.
6. **Ingestão ao vivo** — botão play alimenta `readings_live`, coleção time series
   separada com TTL de 1 h; a tela repinta sozinha a cada 1,5 s.
7. **Ciclo de vida** — `expireAfterSeconds` no quente, Online Archive no frio, uma
   query lendo os dois (depende do tier; ver `LIMITATIONS.md`).

**Não** prova ingestão de milhões de pontos por segundo, time series shardada, nem
benchmark contra InfluxDB/Timescale. Ler `LIMITATIONS.md` antes de qualquer
apresentação.

Portas: backend **8400**, frontend **5400**. Banco: `energia_medicao`.

## Estado

Construído e rodando contra o Atlas real (M20, MongoDB 9.0). Base:
**58.820.400 medições**, 19.980 medidores + 444 fronteiras, 30 dias — 464 MB de dados
e 80 MB de índice, banco `energia_medicao`.

Medido: 35 casos hostis passando, carga misturada sem 5xx até 64 clientes, curva de 30
dias em 16,3 ms sobre um piso de rede de 8,5 ms, e o balanço batendo com a verdade de
terra dentro de 0,3 ponto percentual. Números em `queries/benchmarks.md`.

`bucketMaxSpanSeconds: 86400` foi decidido por medição no ADR 0001, antes do backend
existir, porque não pode ser alterado depois sem reescrever a coleção.

Pendente: o passo 6 do roteiro (Online Archive + Data Federation) exige tier dedicado
e hoje é walkthrough documentado; e o registro em `pov-portfolio/povs.json`, que muda a
contagem esperada pelo `stress_switching.py`.

## Comandos

```bash
# setup
python3 -m venv .venv && .venv/bin/pip install -r data-generator/requirements.txt
python3 -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)

# dados
bash data-generator/run_all.sh                     # ativos + leituras + amostra + índices
METERS=5000 DAYS=7 bash data-generator/run_all.sh  # volume reduzido
.venv/bin/python data-generator/generate_assets.py --drop
.venv/bin/python data-generator/generate_readings.py --drop   # time series não tem upsert
mongosh "$MONGODB_URI" schema/indexes.js

# rodar
./start.sh                    # 8400 + 5400, bundle pronto
POV_DEV=1 ./start.sh          # HMR + uvicorn --reload

# medições
.venv/bin/python queries/bench.py --runs 30        # regrava queries/bench-results.json
.venv/bin/python queries/bucket_experiment.py      # fecha o ADR 0001
.venv/bin/python tests/test_resilience.py          # suíte hostil
.venv/bin/python tests/stress.py                   # carga misturada

# frontend
(cd frontend && npm run build)
```

## Convenções

- Nenhuma rota importa `pymongo`. Query vive em `backend/app/db/`.
- `meta` carrega identidade (`meter_id`, `transformer_id`, `feeder_id`, `phase`,
  `kind`) e nada mutável. Tarifa e classe ficam em `meters` e entram por join na consulta.
- Ponto preenchido por `$fill` sempre volta marcado (`filled: true` + método) e o
  gráfico desenha tracejado. Nunca inventar leitura de energia sem rótulo.
- O servidor escolhe a granularidade a partir do intervalo pedido; o cliente pede
  faixa, não `$dateTrunc`.
- `maxTimeMS` e teto de faixa em toda agregação (`TS_MAX_TIME_MS`,
  `TS_MAX_RANGE_DAYS`).
- O backend nunca escreve em `readings`. Medição é fato de campo; caso é opinião e
  mora em `investigations`.
- Change stream observa `investigations`, não a coleção time series.
- Ingestão ao vivo escreve em `readings_live`, nunca em `readings`: a base histórica é
  a evidência conferida contra a verdade de terra e não pode receber dado novo no meio
  da demo.
- O dado ao vivo é carimbado com **tempo real**, não com o relógio simulado. Carimbar o
  simulado (que continua de onde a base histórica termina, horas no passado) fazia a
  TTL apagar a série em menos de um minuto.
- O gráfico é criado uma vez e recebe `setData`; recriar a cada poll matava cursor e
  zoom no meio da apresentação.
- A camada de dados (`app/db/`) não importa `fastapi`: erro de domínio sobe como
  exceção própria e `main.py` traduz em status. É o simétrico da regra acima.
- `/health` lê a contagem de `dataset_info`; `estimated_document_count()` em 58 M
  medições custa 3 s e é a primeira chamada da tela.
- Bench logo depois de uma carga em massa mede a carga, não o workload — o piso de
  rede subiu de 8,5 ms para 281 ms nessa janela. Espere o cluster silenciar.
- Interface em pt-BR, documentação do repositório em inglês, comentários de código em
  português.
- Antes de mexer no frontend, ler `POV_UI_DESIGN_SYSTEM.md` na raiz do workspace.
