import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Badge from '@leafygreen-ui/badge'
import Button from '@leafygreen-ui/button'
import Banner from '@leafygreen-ui/banner'
import Toggle from '@leafygreen-ui/toggle'
import { api } from './api.js'
import Chart from './Chart.jsx'
import QueryDetails from './QueryDetails.jsx'

const FAIXAS = [
  { label: '1 dia', days: 1 },
  { label: '7 dias', days: 7 },
  { label: '30 dias', days: 30 },
]

function n(value, casas = 2) {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas })
}

function mb(bytes) {
  if (bytes == null) return '—'
  return `${(bytes / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState(null)
  const [transformers, setTransformers] = useState([])
  const [scenarios, setScenarios] = useState(null)
  const [transformerId, setTransformerId] = useState(null)
  const [days, setDays] = useState(7)
  const [modo, setModo] = useState('balance')
  const [meterId, setMeterId] = useState(null)
  const [meters, setMeters] = useState([])
  const [fill, setFill] = useState(true)
  const [balance, setBalance] = useState(null)
  const [curve, setCurve] = useState(null)
  const [storage, setStorage] = useState(null)
  const [aba, setAba] = useState('ativo')
  const [alertas, setAlertas] = useState([])
  const [casos, setCasos] = useState([])
  const [ocupado, setOcupado] = useState(false)
  const streamRef = useRef(null)

  // ---------------------------------------------------------------- carga inicial
  useEffect(() => {
    let vivo = true
    Promise.all([api.health(), api.transformers(), api.scenarios(), api.cases()])
      .then(([h, t, s, c]) => {
        if (!vivo) return
        setHealth(h)
        setTransformers(t.transformers)
        setScenarios(s)
        setCasos(c.cases)
        // Abre no cenário mais severo: a tese da tela é um transformador perdendo energia.
        const alvo = s.scenarios?.[0]?.transformer_id ?? t.transformers[0]?.transformer_id
        setTransformerId(alvo)
      })
      .catch((e) => vivo && setErro(e.message))
      .finally(() => vivo && setCarregando(false))
    return () => { vivo = false }
  }, [])

  // ------------------------------------------------------------------- streaming
  useEffect(() => {
    const es = api.stream()
    streamRef.current = es
    es.addEventListener('alert', (evt) => {
      const alerta = JSON.parse(evt.data)
      setAlertas((prev) => [alerta, ...prev].slice(0, 20))
      api.cases().then((c) => setCasos(c.cases)).catch(() => {})
    })
    es.onerror = () => setHealth((h) => (h ? { ...h, change_stream: 'reconectando' } : h))
    return () => es.close()
  }, [])

  // ---------------------------------------------------------------------- dados
  const carregarBalanco = useCallback(async () => {
    if (!transformerId) return
    setOcupado(true)
    try {
      setBalance(await api.balance(transformerId, days))
      setErro(null)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }, [transformerId, days])

  const carregarCurva = useCallback(async () => {
    if (!meterId) return
    setOcupado(true)
    try {
      setCurve(await api.curve(meterId, days, fill))
      setErro(null)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }, [meterId, days, fill])

  useEffect(() => { if (modo === 'balance') carregarBalanco() }, [modo, carregarBalanco])
  useEffect(() => { if (modo === 'curva') carregarCurva() }, [modo, carregarCurva])

  useEffect(() => {
    if (!transformerId) return
    api.meters(transformerId).then((m) => setMeters(m.meters)).catch(() => setMeters([]))
  }, [transformerId])

  useEffect(() => {
    if (aba === 'armazenamento' && !storage) {
      api.storage().then(setStorage).catch((e) => setErro(e.message))
    }
  }, [aba, storage])

  // --------------------------------------------------------------------- ações
  const cenario = useMemo(
    () => scenarios?.scenarios?.find((s) => s.transformer_id === transformerId) ?? null,
    [scenarios, transformerId],
  )
  const transformador = useMemo(
    () => transformers.find((t) => t.transformer_id === transformerId) ?? null,
    [transformers, transformerId],
  )

  async function abrirCaso() {
    if (!balance?.suspeito) return
    const alvo = cenario?.fraud_meters?.[0] ?? meters[0]?.meter_id
    if (!alvo) return
    setOcupado(true)
    try {
      await api.openCase({
        meter_id: alvo,
        transformer_id: transformerId,
        gap_kwh: balance.totals.gap_kwh,
        gap_pct: balance.totals.gap_pct,
        windows: balance.longest_streak,
        opened_by: 'demo',
      })
      setErro(null)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  async function reiniciar() {
    setOcupado(true)
    try {
      await api.reset()
      setAlertas([])
      setCasos([])
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  const pontos = modo === 'balance' ? balance?.points ?? [] : curve?.points ?? []
  const atual = modo === 'balance' ? balance : curve
  const medidorOutage = scenarios?.demo_meters?.outage?.meter_id

  return (
    <div className="app" data-pov-shell>
      <a className="pov-skip-link" href="#conteudo-principal">Pular para o conteúdo</a>

      <header className="topbar">
        <div className="brand">
          <span className="leaf" aria-hidden="true" />
          <strong>Medição inteligente</strong>
          <span className="tese">a série, o ativo e o caso no mesmo cluster</span>
        </div>
        <div className="status">
          {health?.readings != null && (
            <Badge variant="blue">{health.readings.toLocaleString('pt-BR')} medições</Badge>
          )}
          <Badge variant={health?.change_stream === 'ativo' ? 'green' : 'yellow'}>
            change stream: {health?.change_stream ?? '—'}
          </Badge>
          {/* Carregando não é falha: pintar "sem conexão" enquanto o health responde
              mostra vermelho para a plateia por três segundos sem nada estar errado. */}
          <Badge variant={health?.status === 'ok' ? 'green' : carregando ? 'blue' : 'red'}>
            {health?.status === 'ok' ? 'Atlas conectado' : carregando ? 'conectando…' : 'sem conexão'}
          </Badge>
        </div>
      </header>

      {erro && (
        <Banner variant="danger" className="erro">
          {erro} — verifique se a API responde em {api.base}
        </Banner>
      )}

      <main className="workspace" id="conteudo-principal">
        <aside className="rail">
          <label className="campo">
            <span>Transformador</span>
            <select value={transformerId ?? ''} onChange={(e) => setTransformerId(e.target.value)}>
              {transformers.map((t) => (
                <option key={t.transformer_id} value={t.transformer_id}>
                  {t.transformer_id}
                  {t.scenario ? ` · ${t.scenario.kind}` : ''}
                </option>
              ))}
            </select>
          </label>

          <div className="campo">
            <span>Faixa</span>
            <div className="segmentado" role="group" aria-label="Faixa de tempo">
              {FAIXAS.map((f) => (
                <button key={f.days} type="button" aria-pressed={days === f.days}
                        className={days === f.days ? 'ativo' : ''}
                        onClick={() => setDays(f.days)}>{f.label}</button>
              ))}
            </div>
          </div>

          <div className="campo">
            <span>Visão</span>
            <div className="segmentado" role="group" aria-label="Visão">
              <button type="button" aria-pressed={modo === 'balance'}
                      className={modo === 'balance' ? 'ativo' : ''}
                      onClick={() => setModo('balance')}>Balanço</button>
              <button type="button" aria-pressed={modo === 'curva'}
                      className={modo === 'curva' ? 'ativo' : ''}
                      onClick={() => { setModo('curva'); if (!meterId) setMeterId(medidorOutage ?? meters[0]?.meter_id) }}>
                Curva
              </button>
            </div>
          </div>

          {modo === 'curva' && (
            <>
              <label className="campo">
                <span>Medidor</span>
                <select value={meterId ?? ''} onChange={(e) => setMeterId(e.target.value)}>
                  {medidorOutage && <option value={medidorOutage}>{medidorOutage} · falha de comunicação</option>}
                  {meters.filter((m) => m.meter_id !== medidorOutage).map((m) => (
                    <option key={m.meter_id} value={m.meter_id}>{m.meter_id} · {m.customer_class}</option>
                  ))}
                </select>
              </label>
              <div className="campo linha">
                <span>Reconstruir lacuna</span>
                <Toggle size="small" checked={fill} onChange={setFill} aria-label="Reconstruir lacuna" />
              </div>
            </>
          )}

          <div className="acoes">
            <Button variant="primary" disabled={!balance?.suspeito || ocupado} onClick={abrirCaso}>
              Abrir investigação
            </Button>
            <Button variant="default" disabled={ocupado} onClick={reiniciar}>Reiniciar demo</Button>
          </div>

          {cenario && (
            <div className="verdade">
              <strong>Verdade de terra</strong>
              <p>{cenario.label}</p>
              <dl>
                <div><dt>gap esperado</dt><dd>{n(cenario.expected_gap_pct)}%</dd></div>
                <div><dt>perda técnica</dt><dd>{n(cenario.technical_loss * 100)}%</dd></div>
                <div><dt>deve abrir caso</dt><dd>{cenario.should_open_case ? 'sim' : 'não (controle)'}</dd></div>
              </dl>
              <small>gerada pelo seed; a tela confere o balanço contra ela</small>
            </div>
          )}
        </aside>

        <section className="palco">
          <div className="metricas">
            {modo === 'balance' ? (
              <>
                <Metrica rotulo="entregue" valor={`${n(balance?.totals?.entregue_kwh, 0)} kWh`} />
                <Metrica rotulo="registrado" valor={`${n(balance?.totals?.registrado_kwh, 0)} kWh`} />
                <Metrica rotulo="diferença" valor={`${n(balance?.totals?.gap_kwh, 0)} kWh`} destaque="risco" />
                <Metrica rotulo="gap" valor={`${n(balance?.totals?.gap_pct)}%`} destaque={balance?.suspeito ? 'risco' : 'ok'} />
                <Metrica rotulo="janelas seguidas" valor={balance?.longest_streak ?? '—'} />
                <Metrica rotulo="resposta" valor={`${n(balance?.elapsed_ms, 0)} ms`} />
              </>
            ) : (
              <>
                <Metrica rotulo="pontos" valor={curve?.point_count ?? '—'} />
                <Metrica rotulo="reconstruídos" valor={curve?.filled_count ?? '—'} destaque={curve?.filled_count ? 'alerta' : undefined} />
                <Metrica rotulo="método" valor={fill ? 'linear · $fill' : 'sem preenchimento'} />
                <Metrica rotulo="resposta" valor={`${n(curve?.elapsed_ms, 0)} ms`} />
              </>
            )}
            <div className="granularidade">
              agregação do servidor: <strong>{atual?.granularity?.label ?? '—'}</strong>
            </div>
          </div>

          {modo === 'balance' && balance && (
            <p className={`veredito ${balance.suspeito ? 'risco' : 'ok'}`}>
              {balance.suspeito
                ? `média móvel acima de ${n(balance.threshold_pct, 0)}% por ${balance.longest_streak} janelas seguidas — suspeita de perda não técnica`
                : `gap dentro da faixa técnica; ${balance.longest_streak} janelas acima do limiar de ${n(balance.threshold_pct, 0)}% — nada a investigar`}
            </p>
          )}

          {pontos.length > 0
            ? <Chart mode={modo === 'balance' ? 'balance' : 'curve'} points={pontos} />
            : <div className="vazio">
                {carregando || ocupado
                  ? 'consultando o cluster…'
                  : 'sem pontos nesta faixa — escolha outro intervalo'}
              </div>}

          <QueryDetails pipeline={atual?.pipeline}
                        namespace={`${health?.database ?? 'energia_medicao'}.readings`}
                        elapsedMs={atual?.elapsed_ms} />
        </section>

        <aside className="inspector">
          <div className="abas" role="tablist">
            {['ativo', 'armazenamento', 'casos'].map((t) => (
              <button key={t} role="tab" aria-selected={aba === t}
                      className={aba === t ? 'ativo' : ''} onClick={() => setAba(t)}>
                {t === 'ativo' ? 'Ativo' : t === 'armazenamento' ? 'Armazenamento' : 'Casos'}
              </button>
            ))}
          </div>

          <div className="corpo">
            {aba === 'ativo' && transformador && (
              <dl className="detalhe">
                <div><dt>transformador</dt><dd>{transformador.transformer_id}</dd></div>
                <div><dt>alimentador</dt><dd>{transformador.feeder_id}</dd></div>
                <div><dt>capacidade</dt><dd>{transformador.capacity_kva} kVA</dd></div>
                <div><dt>instalado</dt><dd>{transformador.installed_year}</dd></div>
                <div><dt>medidores</dt><dd>{transformador.meter_count}</dd></div>
                <div><dt>medidor de fronteira</dt><dd>{transformador.boundary_meter_id}</dd></div>
                <div><dt>perda técnica</dt><dd>{n(transformador.technical_loss * 100)}%</dd></div>
              </dl>
            )}

            {aba === 'armazenamento' && (
              storage?.available ? (
                <>
                  {/* Duas fichas empilhadas em vez de uma tabela: cinco colunas
                      não cabem nos 320 px do inspetor e a última era cortada. */}
                  {[
                    { dados: storage.timeseries, rotulo: 'readings', badge: 'time series' },
                    { dados: storage.flat, rotulo: 'readings_flat', badge: null },
                  ].map(({ dados, rotulo, badge }) => (
                    <div className="ficha" key={rotulo}>
                      <header>
                        <code>{rotulo}</code>
                        {badge && <Badge variant="green">{badge}</Badge>}
                      </header>
                      <dl className="detalhe">
                        <div><dt>medições</dt><dd>{dados.documents.toLocaleString('pt-BR')}</dd></div>
                        <div><dt>dados</dt><dd>{mb(dados.storage_bytes)}</dd></div>
                        <div><dt>índice</dt><dd>{mb(dados.index_bytes)}</dd></div>
                        <div><dt>bytes/medição</dt><dd>{n(dados.bytes_per_measurement)}</dd></div>
                      </dl>
                    </div>
                  ))}
                  <p className="razao">
                    <strong>{n(storage.storage_ratio)}×</strong> menos armazenamento por medição,
                    <strong> {n(storage.total_ratio)}×</strong> contando o índice.
                  </p>
                  <small>{storage.note}. Buckets: {storage.timeseries.buckets?.toLocaleString('pt-BR') ?? '—'}.</small>
                </>
              ) : <p className="vazio">{storage?.reason ?? 'medindo…'}</p>
            )}

            {aba === 'casos' && (
              casos.length ? (
                <ul className="casos">
                  {casos.map((c) => (
                    <li key={c.case_id}>
                      <strong>{c.case_id}</strong>
                      <span>{c.meter_id} · {c.transformer_id}</span>
                      <span>{n(c.evidence?.gap_pct)}% · {n(c.evidence?.gap_kwh, 0)} kWh</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="vazio">nenhum caso aberto</p>
            )}
          </div>
        </aside>
      </main>

      <footer className="tira" aria-live="polite">
        <span className="rotulo">alertas (change stream)</span>
        {alertas.length === 0
          ? <span className="vazio">nenhum alerta — abra uma investigação</span>
          : alertas.map((a) => (
              <span className="alerta" key={`${a.case_id}-${a.at}`}>
                <Badge variant="red">{a.case_id}</Badge>
                {a.meter_id} · {a.transformer_id} · {n(a.gap_pct)}%
              </span>
            ))}
      </footer>
    </div>
  )
}

function Metrica({ rotulo, valor, destaque }) {
  return (
    <div className={`metrica${destaque ? ` ${destaque}` : ''}`}>
      <span className="rotulo">{rotulo}</span>
      <strong className="valor">{valor}</strong>
    </div>
  )
}
