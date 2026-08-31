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
  const [hover, setHover] = useState(null)
  const [live, setLive] = useState(null)
  const [aviso, setAviso] = useState(null)
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
  const aoVivo = live?.state === 'rodando'

  const carregarBalanco = useCallback(async (silencioso = false) => {
    if (!transformerId) return
    if (!silencioso) setOcupado(true)
    try {
      setBalance(await api.balance(transformerId, days, aoVivo))
      setErro(null)
    } catch (e) { setErro(e.message) } finally { if (!silencioso) setOcupado(false) }
  }, [transformerId, days, aoVivo])

  const carregarCurva = useCallback(async (silencioso = false) => {
    if (!meterId) return
    if (!silencioso) setOcupado(true)
    try {
      setCurve(await api.curve(meterId, days, fill, aoVivo))
      setErro(null)
    } catch (e) { setErro(e.message) } finally { if (!silencioso) setOcupado(false) }
  }, [meterId, days, fill, aoVivo])

  useEffect(() => { if (modo === 'balance') carregarBalanco() }, [modo, carregarBalanco])
  useEffect(() => { if (modo === 'curva') carregarCurva() }, [modo, carregarCurva])

  useEffect(() => {
    if (!transformerId) return
    api.meters(transformerId).then((m) => setMeters(m.meters)).catch(() => setMeters([]))
  }, [transformerId])

  // Enquanto a ingestão roda, a tela repinta sozinha. Silencioso: marcar "ocupado" a
  // cada 1,5 s faria o gráfico piscar durante a demo inteira.
  useEffect(() => {
    if (!aoVivo) return undefined
    const t = setInterval(() => {
      api.liveStatus().then(setLive).catch(() => {})
      if (modo === 'balance') carregarBalanco(true)
      else carregarCurva(true)
    }, 1500)
    return () => clearInterval(t)
  }, [aoVivo, modo, carregarBalanco, carregarCurva])

  useEffect(() => {
    api.liveStatus().then(setLive).catch(() => {})
  }, [])

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

  async function alternarLive() {
    setOcupado(true)
    try {
      const st = aoVivo ? await api.liveStop() : await api.liveStart(transformerId)
      setLive(st)
      setAviso(aoVivo ? 'ingestão parada' : `ingestão ao vivo em ${transformerId}`)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  async function reiniciar() {
    setOcupado(true)
    try {
      const r = await api.reset()
      setAlertas([])
      setCasos([])
      setLive(r.ao_vivo ?? null)
      setHover(null)
      // Reiniciar sem repintar parecia não fazer nada: o backend limpava e a tela
      // continuava mostrando o estado anterior.
      await Promise.all([api.health().then(setHealth), api.scenarios().then(setScenarios)])
      if (modo === 'balance') await carregarBalanco()
      else await carregarCurva()
      setAviso(`demo reiniciada — ${r.cases_removidos} caso(s), ${r.alertas_removidos} alerta(s) removidos`)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  useEffect(() => {
    if (!aviso) return undefined
    const t = setTimeout(() => setAviso(null), 4000)
    return () => clearTimeout(t)
  }, [aviso])

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
          {aoVivo && <Badge variant="red">ingerindo ao vivo</Badge>}
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

      {aviso && !erro && <Banner variant="info" className="erro">{aviso}</Banner>}

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
            <Button variant={aoVivo ? 'danger' : 'primaryOutline'} disabled={ocupado || !transformerId}
                    onClick={alternarLive}>
              {aoVivo ? '■ Parar ingestão' : '▶ Iniciar ingestão ao vivo'}
            </Button>
            <Button variant="primary" disabled={!balance?.suspeito || ocupado} onClick={abrirCaso}>
              Abrir investigação
            </Button>
            <Button variant="default" disabled={ocupado} onClick={reiniciar}>Reiniciar demo</Button>
          </div>

          {live && (live.state === 'rodando' || live.written > 0) && (
            <div className="live-box">
              <header>
                <span className={`ponto${aoVivo ? ' pulsando' : ''}`} aria-hidden="true" />
                <strong>{aoVivo ? 'ingerindo' : 'ingestão parada'}</strong>
              </header>
              <dl>
                <div><dt>medições gravadas</dt><dd>{live.written.toLocaleString('pt-BR')}</dd></div>
                <div><dt>relógio simulado</dt>
                  <dd>{live.simulated_now
                    ? new Date(live.simulated_now).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
                    : '—'}</dd></div>
                <div><dt>ritmo</dt><dd>{live.minutes_per_tick} min / {live.tick_seconds}s</dd></div>
                <div><dt>TTL</dt><dd>{Math.round(live.ttl_seconds / 60)} min</dd></div>
              </dl>
              <small>
                coleção <code>{live.collection}</code>, separada da base histórica e com
                TTL — o dado ao vivo expira sozinho e o roteiro roda de novo.
              </small>
            </div>
          )}

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
              {hover ? (
                <span className="leitura">
                  <strong>{new Date(hover.ts).toLocaleString('pt-BR', {
                    day: '2-digit', month: '2-digit', hour: '2-digit',
                    minute: '2-digit', second: atual?.granularity?.unit === 'second' ? '2-digit' : undefined,
                  })}</strong>
                  {modo === 'balance'
                    ? ` · entregue ${n(hover.entregue)} · registrado ${n(hover.registrado)} · gap ${n(hover.gap_pct)}%`
                    : ` · ${n(hover.kwh, 4)} kWh${hover.filled ? ' · reconstruído' : ''}`}
                </span>
              ) : (
                <>agregação do servidor: <strong>{atual?.granularity?.label ?? '—'}</strong></>
              )}
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
            ? <Chart mode={modo === 'balance' ? 'balance' : 'curve'} points={pontos}
                     onHover={setHover} />
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
