import { useCallback, useEffect, useMemo, useState } from 'react'
import Badge from '@leafygreen-ui/badge'
import Button from '@leafygreen-ui/button'
import Banner from '@leafygreen-ui/banner'
import { api } from './api.js'
import Chart from './Chart.jsx'
import QueryDetails from './QueryDetails.jsx'

const JANELAS = [
  { label: '1 h', hours: 1 },
  { label: '6 h', hours: 6 },
  { label: '24 h', hours: 24 },
  { label: '7 d', hours: 168 },
]

const CANAIS = [
  { id: 'pix', label: 'PIX' },
  { id: 'cartao', label: 'Cartão' },
  { id: 'ted', label: 'TED' },
]

function n(valor, casas = 2) {
  if (valor == null || Number.isNaN(valor)) return '—'
  return valor.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas })
}

function inteiro(valor) {
  return valor == null ? '—' : valor.toLocaleString('pt-BR')
}

function mb(bytes) {
  if (bytes == null) return '—'
  return `${(bytes / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState(null)
  const [aviso, setAviso] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  const [canal, setCanal] = useState('pix')
  const [provedores, setProvedores] = useState([])
  const [provedorId, setProvedorId] = useState(null)
  const [hours, setHours] = useState(24)
  const [modo, setModo] = useState('saude')
  const [fill, setFill] = useState(true)

  const [serie, setSerie] = useState(null)
  const [saude, setSaude] = useState(null)
  const [ranking, setRanking] = useState(null)
  const [storage, setStorage] = useState(null)
  const [cenarios, setCenarios] = useState(null)
  const [incidentes, setIncidentes] = useState([])
  const [alertas, setAlertas] = useState([])
  const [hover, setHover] = useState(null)
  const [aba, setAba] = useState('provedor')

  const [live, setLive] = useState(null)
  const [conta, setConta] = useState('')
  const [velocity, setVelocity] = useState(null)

  const aoVivo = live?.state === 'rodando'

  // ---------------------------------------------------------------- carga inicial
  useEffect(() => {
    let vivo = true
    Promise.all([api.health(), api.scenarios(), api.incidents(), api.liveStatus()])
      .then(([h, s, i, l]) => {
        if (!vivo) return
        setHealth(h); setCenarios(s); setIncidentes(i.incidents); setLive(l)
        // Abre no cenário de recusa: é o passo 4 do roteiro e cabe na janela de
        // 24 h. O de latência foi plantado há dois dias de propósito e precisa de 72 h.
        const degradado = s.scenarios?.find((x) => x.kind === 'recusa')
          ?? s.scenarios?.find((x) => x.deve_abrir_incidente)
        if (degradado) { setCanal(degradado.canal); setProvedorId(degradado.provedor_id) }
        const c = s.demo_accounts?.[0]?.conta_id
        if (c) setConta(c)
      })
      .catch((e) => vivo && setErro(e.message))
      .finally(() => vivo && setCarregando(false))
    return () => { vivo = false }
  }, [])

  useEffect(() => {
    api.providers(canal).then((p) => {
      setProvedores(p.providers)
      setProvedorId((atual) => (p.providers.some((x) => x.provedor_id === atual)
        ? atual : p.providers[0]?.provedor_id ?? null))
    }).catch(() => setProvedores([]))
  }, [canal])

  // ------------------------------------------------------------------- streaming
  useEffect(() => {
    const es = api.stream()
    es.addEventListener('alert', (evt) => {
      setAlertas((prev) => [JSON.parse(evt.data), ...prev].slice(0, 20))
      api.incidents().then((i) => setIncidentes(i.incidents)).catch(() => {})
    })
    es.onerror = () => setHealth((h) => (h ? { ...h, change_stream: 'reconectando' } : h))
    return () => es.close()
  }, [])

  // ---------------------------------------------------------------------- dados
  const carregar = useCallback(async (silencioso = false) => {
    if (!provedorId) return
    if (!silencioso) setOcupado(true)
    try {
      if (modo === 'saude') {
        setSaude(aoVivo ? await api.liveHealth(provedorId) : await api.providerHealth(provedorId, hours))
      } else {
        setSerie(await api.latency(canal, provedorId, hours, fill))
      }
      setErro(null)
    } catch (e) { setErro(e.message) } finally { if (!silencioso) setOcupado(false) }
  }, [provedorId, modo, hours, canal, fill, aoVivo])

  useEffect(() => { carregar() }, [carregar])

  useEffect(() => {
    if (!aoVivo) return undefined
    // Silencioso: marcar "ocupado" a cada 1,5 s faria o gráfico piscar a demo inteira.
    const t = setInterval(() => {
      api.liveStatus().then(setLive).catch(() => {})
      carregar(true)
    }, 1500)
    return () => clearInterval(t)
  }, [aoVivo, carregar])

  useEffect(() => {
    if (aba === 'armazenamento' && !storage) {
      api.storage().then(setStorage).catch((e) => setErro(e.message))
    }
    if (aba === 'ranking' && !ranking) {
      // Janela fixa de 1 h: o placar varre todos os provedores e em 24 h não cabe
      // no teto de 15 s. "Quem está ruim agora" é a pergunta dele.
      api.ranking(1).then(setRanking).catch((e) => setErro(e.message))
    }
  }, [aba, storage, ranking])

  useEffect(() => {
    if (!aviso) return undefined
    const t = setTimeout(() => setAviso(null), 4500)
    return () => clearTimeout(t)
  }, [aviso])

  // --------------------------------------------------------------------- ações
  const cenario = useMemo(
    () => cenarios?.scenarios?.find((s) => s.provedor_id === provedorId) ?? null,
    [cenarios, provedorId],
  )
  const provedor = useMemo(
    () => provedores.find((p) => p.provedor_id === provedorId) ?? null,
    [provedores, provedorId],
  )

  async function consultarVelocity() {
    if (!conta) return
    setOcupado(true)
    try { setVelocity(await api.velocity(conta.trim())); setErro(null) }
    catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  async function abrirIncidente() {
    if (!saude?.degradado) return
    setOcupado(true)
    try {
      await api.openIncident({
        provedor_id: provedorId,
        canal: provedor?.canal ?? canal,
        // API de incidentes mantém o campo `z_recusa` (contrato de evidência); em modo
        // ao vivo o valor enviado é a razão percentual (`delta_ratio_recusa_max`), não
        // um z-score real — não há linha de base aprendida na janela ao vivo.
        z_recusa: aoVivo ? (saude.pico?.delta_ratio_recusa_max ?? 0) : (saude.pico?.z_recusa_max ?? 0),
        z_p99: aoVivo ? 0 : (saude.pico?.z_p99_max ?? 0),
        janelas: saude.longest_streak,
        taxa_recusa: saude.totals.taxa_recusa,
        p99_ms: saude.points.at(-1)?.p99 ?? 0,
        eventos: saude.totals.eventos,
        aberto_por: 'demo',
      })
      setErro(null)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  async function alternarLive() {
    setOcupado(true)
    try {
      const st = aoVivo ? await api.liveStop() : await api.liveStart(canal, 40)
      setLive(st)
      setAviso(aoVivo ? 'ingestão parada' : `ingestão ao vivo no canal ${canal}`)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  async function alternarDegradacao() {
    setOcupado(true)
    try {
      const alvo = live?.degradado ? null : provedorId
      setLive(await api.liveDegrade(alvo))
      setAviso(alvo ? `degradação injetada em ${alvo}` : 'degradação removida')
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  async function reiniciar() {
    setOcupado(true)
    try {
      const r = await api.reset()
      setAlertas([]); setIncidentes([]); setLive(r.ao_vivo ?? null); setHover(null)
      // Reiniciar sem repintar parecia não fazer nada: o backend limpava e a tela
      // continuava mostrando o estado anterior.
      await Promise.all([api.health().then(setHealth), api.scenarios().then(setCenarios)])
      await carregar()
      setAviso(`demo reiniciada — ${r.incidentes_removidos} incidente(s), ${r.alertas_removidos} alerta(s)`)
    } catch (e) { setErro(e.message) } finally { setOcupado(false) }
  }

  const atual = modo === 'saude' ? saude : serie
  const pontos = atual?.points ?? []
  const ultimo = pontos.at(-1) ?? {}

  return (
    <div className="app" data-pov-shell>
      <a className="pov-skip-link" href="#conteudo-principal">Pular para o conteúdo</a>

      <header className="topbar">
        <div className="brand">
          <span className="leaf" aria-hidden="true" />
          <strong>Trilho de pagamentos</strong>
          <span className="tese">o evento, a rota e o incidente no mesmo cluster</span>
        </div>
        <div className="status">
          {health?.events != null && <Badge variant="blue">{inteiro(health.events)} eventos</Badge>}
          {aoVivo && <Badge variant="red">ingerindo ao vivo</Badge>}
          {live?.degradado && <Badge variant="yellow">degradando {live.degradado}</Badge>}
          <Badge variant={health?.change_stream === 'ativo' ? 'green' : 'yellow'}>
            change stream: {health?.change_stream ?? '—'}
          </Badge>
          {/* Carregando não é falha: pintar "sem conexão" enquanto o health responde
              mostra vermelho para a plateia sem nada estar errado. */}
          <Badge variant={health?.status === 'ok' ? 'green' : carregando ? 'blue' : 'red'}>
            {health?.status === 'ok' ? 'Atlas conectado' : carregando ? 'conectando…' : 'sem conexão'}
          </Badge>
        </div>
      </header>

      {aviso && !erro && <Banner variant="info" className="erro">{aviso}</Banner>}
      {erro && <Banner variant="danger" className="erro">{erro} — verifique a API em {api.base}</Banner>}

      <main className="workspace" id="conteudo-principal">
        <aside className="rail">
          <div className="campo">
            <span>Canal</span>
            <div className="segmentado" role="group" aria-label="Canal">
              {CANAIS.map((c) => (
                <button key={c.id} type="button" aria-pressed={canal === c.id}
                        className={canal === c.id ? 'ativo' : ''}
                        onClick={() => setCanal(c.id)}>{c.label}</button>
              ))}
            </div>
          </div>

          <label className="campo">
            <span>Provedor</span>
            <select value={provedorId ?? ''} onChange={(e) => {
              // O canal acompanha o provedor: escolher um PSP de PIX com o canal em
              // Cartão produzia um par contraditório e uma tela vazia.
              const p = provedores.find((x) => x.provedor_id === e.target.value)
              if (p && p.canal !== canal) setCanal(p.canal)
              setProvedorId(e.target.value)
            }}>
              {provedores.map((p) => (
                <option key={p.provedor_id} value={p.provedor_id}>
                  {p.provedor_id} · recusa base {n(p.recusa_base * 100)}%
                </option>
              ))}
            </select>
          </label>

          <div className="campo">
            <span>Janela</span>
            <div className="segmentado" role="group" aria-label="Janela">
              {JANELAS.map((j) => (
                <button key={j.hours} type="button" aria-pressed={hours === j.hours}
                        className={hours === j.hours ? 'ativo' : ''}
                        disabled={aoVivo}
                        onClick={() => setHours(j.hours)}>{j.label}</button>
              ))}
            </div>
          </div>

          <div className="campo">
            <span>Visão</span>
            <div className="segmentado" role="group" aria-label="Visão">
              <button type="button" aria-pressed={modo === 'saude'}
                      className={modo === 'saude' ? 'ativo' : ''}
                      onClick={() => setModo('saude')}>Recusa</button>
              <button type="button" aria-pressed={modo === 'latencia'}
                      className={modo === 'latencia' ? 'ativo' : ''}
                      disabled={aoVivo}
                      onClick={() => setModo('latencia')}>Latência</button>
            </div>
          </div>

          <div className="acoes">
            <Button variant={aoVivo ? 'danger' : 'primaryOutline'} disabled={ocupado}
                    onClick={alternarLive}>
              {aoVivo ? '■ Parar ingestão' : '▶ Iniciar ingestão ao vivo'}
            </Button>
            {aoVivo && (
              <Button variant={live?.degradado ? 'default' : 'dangerOutline'} disabled={ocupado}
                      onClick={alternarDegradacao}>
                {live?.degradado ? 'Remover degradação' : '⚡ Injetar degradação'}
              </Button>
            )}
            <Button variant="primary" disabled={!saude?.degradado || ocupado}
                    onClick={abrirIncidente}>Abrir incidente</Button>
            <Button variant="default" disabled={ocupado} onClick={reiniciar}>Reiniciar demo</Button>
          </div>

          {live && (live.state === 'rodando' || live.written > 0) && (
            <div className="live-box">
              <header>
                <span className={`ponto${aoVivo ? ' pulsando' : ''}`} aria-hidden="true" />
                <strong>{aoVivo ? 'ingerindo' : 'ingestão parada'}</strong>
              </header>
              <dl>
                <div><dt>eventos gravados</dt><dd>{inteiro(live.written)}</dd></div>
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
                <div><dt>recusa base</dt><dd>{n(cenario.recusa_base * 100)}%</dd></div>
                <div><dt>recusa esperada</dt><dd>{n(cenario.recusa_esperada * 100)}%</dd></div>
                <div><dt>latência</dt><dd>×{n(cenario.fator_latencia, 1)}</dd></div>
                <div><dt>deve abrir</dt><dd>{cenario.deve_abrir_incidente ? 'sim' : 'não (controle)'}</dd></div>
              </dl>
              <small>gerada pelo seed; a tela confere a detecção contra ela</small>
            </div>
          )}
        </aside>

        <section className="palco">
          <div className="metricas">
            {modo === 'saude' ? (
              <>
                <Metrica rotulo="eventos" valor={inteiro(saude?.totals?.eventos)} />
                <Metrica rotulo="recusa" valor={`${n(saude?.totals?.taxa_recusa)}%`}
                         destaque={saude?.degradado ? 'risco' : 'ok'} />
                <Metrica rotulo={aoVivo ? 'variação recusa (pico)' : 'z recusa (pico)'}
                         valor={n(aoVivo ? saude?.pico?.delta_ratio_recusa_max : saude?.pico?.z_recusa_max)}
                         destaque={saude?.degradado ? 'risco' : undefined} />
                {aoVivo ? (
                  <Metrica rotulo="z p99 (pico)" valor="indisponível ao vivo" />
                ) : (
                  <Metrica rotulo="z p99 (pico)" valor={n(saude?.pico?.z_p99_max)} />
                )}
                <Metrica rotulo="janelas seguidas" valor={saude?.longest_streak ?? '—'} />
                <Metrica rotulo="resposta" valor={`${n(saude?.elapsed_ms, 0)} ms`} />
              </>
            ) : (
              <>
                <Metrica rotulo="eventos" valor={inteiro(serie?.points?.reduce((a, p) => a + (p.eventos ?? 0), 0))} />
                <Metrica rotulo="p50" valor={`${n(ultimo.p50, 0)} ms`} />
                <Metrica rotulo="p95" valor={`${n(ultimo.p95, 0)} ms`} />
                <Metrica rotulo="p99" valor={`${n(ultimo.p99, 0)} ms`} destaque="alerta" />
                <Metrica rotulo="reconstruídos" valor={serie?.reconstruidos ?? '—'}
                         destaque={serie?.reconstruidos ? 'alerta' : undefined} />
                <Metrica rotulo="resposta" valor={`${n(serie?.elapsed_ms, 0)} ms`} />
              </>
            )}
            <div className="granularidade">
              {hover ? (
                <span className="leitura">
                  <strong>{new Date(hover.ts).toLocaleString('pt-BR', {
                    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                    second: atual?.granularity?.unit === 'second' ? '2-digit' : undefined,
                  })}</strong>
                  {modo === 'saude'
                    ? ` · recusa ${n(hover.taxa_recusa)}% · base ${n(hover.recusa_base)}% · ${
                        aoVivo ? `Δ ${n(hover.delta_ratio_recusa)}` : `z ${n(hover.z_recusa)}`}`
                    : ` · p50 ${n(hover.p50, 0)} · p95 ${n(hover.p95, 0)} · p99 ${n(hover.p99, 0)} ms${hover.reconstruido ? ' · reconstruído' : ''}`}
                </span>
              ) : (
                <>agregação do servidor: <strong>{atual?.granularity?.label ?? '—'}</strong></>
              )}
            </div>
          </div>

          {modo === 'saude' && saude && (
            <p className={`veredito ${saude.degradado ? 'risco' : 'ok'}`}>
              {/* Ao vivo a referência é a base cadastrada do provedor; no histórico
                  ela é aprendida da própria série. Dizer "3 desvios" nos dois casos
                  seria descrever um critério que não é o que rodou. */}
              {saude.degradado
                ? (saude.live
                    ? `recusa acima de ${n(saude.limite_pct)}% (base cadastrada ${n(saude.recusa_base_pct)}%) por ${saude.longest_streak} janelas seguidas — degradação`
                    : `recusa acima de ${n(saude.z_threshold, 1)} desvios da própria linha de base por ${saude.longest_streak} janelas seguidas — degradação`)
                : (saude.live
                    ? `dentro da base cadastrada do provedor (${n(saude.recusa_base_pct)}%, limite ${n(saude.limite_pct)}%) — nada a abrir`
                    : `dentro da linha de base do provedor; maior sequência anômala: ${saude.longest_streak} janela(s), limiar ${saude.min_windows} — nada a abrir`)}
            </p>
          )}

          {pontos.length > 0
            ? <Chart mode={modo === 'saude' ? 'saude' : 'latencia'} points={pontos} onHover={setHover} />
            : <div className="vazio">
                {carregando || ocupado
                  ? 'consultando o cluster…'
                  : 'sem eventos medidos nesta janela — escolha outro intervalo ou provedor'}
              </div>}

          <QueryDetails pipeline={atual?.pipeline}
                        namespace={`${health?.database ?? 'trilho_pagamentos'}.${aoVivo && modo === 'saude' ? 'payment_events_live' : 'payment_events'}`}
                        elapsedMs={atual?.elapsed_ms} />
        </section>

        <aside className="inspector">
          <div className="abas" role="tablist">
            {[['provedor', 'Provedor'], ['velocity', 'Velocity'],
              ['armazenamento', 'Armaz.'], ['ranking', 'Ranking'],
              ['incidentes', 'Incid.']].map(([id, rotulo]) => (
              <button key={id} role="tab" aria-selected={aba === id}
                      className={aba === id ? 'ativo' : ''} onClick={() => setAba(id)}>{rotulo}</button>
            ))}
          </div>

          <div className="corpo">
            {aba === 'provedor' && provedor && (
              <dl className="detalhe">
                <div><dt>provedor</dt><dd>{provedor.provedor_id}</dd></div>
                <div><dt>canal</dt><dd>{provedor.canal}</dd></div>
                <div><dt>recusa base</dt><dd>{n(provedor.recusa_base * 100)}%</dd></div>
                <div><dt>SLA p99</dt><dd>{inteiro(provedor.sla_p99_ms)} ms</dd></div>
                <div><dt>participação</dt><dd>{n(provedor.participacao)}</dd></div>
                <div><dt>em incidente</dt><dd>{provedor.em_incidente ? 'sim' : 'não'}</dd></div>
              </dl>
            )}

            {aba === 'velocity' && (
              <>
                <p className="explica">
                  Feature que roda <strong>dentro</strong> do fluxo de autorização, não
                  num painel. Uma passada sobre a janela de 24 h, três recortes.
                </p>
                <div className="linha-busca">
                  <input value={conta} onChange={(e) => setConta(e.target.value)}
                         placeholder="C000123456" aria-label="conta" />
                  <Button size="small" disabled={ocupado} onClick={consultarVelocity}>Consultar</Button>
                </div>
                {cenarios?.demo_accounts?.length > 0 && (
                  <div className="chips">
                    {cenarios.demo_accounts.slice(0, 5).map((c) => (
                      <button key={c.conta_id} className="chip"
                              onClick={() => { setConta(c.conta_id); }}>
                        {c.conta_id} · {inteiro(c.eventos_24h)}
                      </button>
                    ))}
                  </div>
                )}
                {velocity && (
                  <>
                    <table className="tabela">
                      <thead><tr><th>janela</th><th>eventos</th><th>valor</th><th>recusa</th></tr></thead>
                      <tbody>
                        {Object.entries(velocity.janelas).map(([k, v]) => (
                          <tr key={k}>
                            <td>{k}</td><td>{inteiro(v.eventos)}</td>
                            <td>{n(v.valor, 0)}</td><td>{n(v.taxa_recusa)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="razao"><strong>{n(velocity.elapsed_ms, 1)} ms</strong> na consulta</p>
                    <small>canais: {velocity.canais.join(', ') || '—'} · UFs: {velocity.ufs.join(', ') || '—'}</small>
                  </>
                )}
              </>
            )}

            {aba === 'armazenamento' && (
              storage?.available ? (
                <>
                  {[{ dados: storage.timeseries, rotulo: 'payment_events', badge: 'time series' },
                    { dados: storage.flat, rotulo: 'payment_events_flat', badge: null }].map(({ dados, rotulo, badge }) => (
                    <div className="ficha" key={rotulo}>
                      <header><code>{rotulo}</code>{badge && <Badge variant="green">{badge}</Badge>}</header>
                      <dl className="detalhe">
                        <div><dt>eventos</dt><dd>{inteiro(dados.documents)}</dd></div>
                        <div><dt>dados</dt><dd>{mb(dados.storage_bytes)}</dd></div>
                        <div><dt>índice</dt><dd>{mb(dados.index_bytes)}</dd></div>
                        <div><dt>bytes/evento</dt><dd>{n(dados.bytes_per_event)}</dd></div>
                      </dl>
                    </div>
                  ))}
                  <p className="razao">
                    <strong>{n(storage.storage_ratio)}×</strong> menos armazenamento por evento,
                    <strong> {n(storage.total_ratio)}×</strong> contando o índice.
                  </p>
                  <small>
                    {storage.note}. Buckets: {inteiro(storage.timeseries.buckets)}.
                    {storage.cached && ` Medido há ${Math.round(storage.measured_seconds_ago)}s.`}
                  </small>
                </>
              ) : <p className="vazio">{storage?.reason ?? 'medindo…'}</p>
            )}

            {aba === 'ranking' && (
              ranking?.providers?.length ? (
                <table className="tabela">
                  <thead><tr><th>provedor</th><th>eventos</th><th>recusa</th><th>p99</th></tr></thead>
                  <tbody>
                    {ranking.providers.slice(0, 20).map((p) => (
                      <tr key={p.provedor} className={p.fora_do_sla ? 'fora' : ''}>
                        <td>{p.provedor}</td><td>{inteiro(p.eventos)}</td>
                        <td>{n(p.taxa_recusa)}%</td>
                        <td>{n(p.p99, 0)}{p.fora_do_sla ? ' ⚠' : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="vazio">medindo…</p>
            )}
            {aba === 'ranking' && ranking && (
              <small>última {ranking.hours}h · todos os provedores</small>
            )}

            {aba === 'incidentes' && (
              incidentes.length ? (
                <ul className="casos">
                  {incidentes.map((i) => (
                    <li key={i.incident_id}>
                      <strong>{i.incident_id}</strong>
                      <span>{i.provedor_id} · {i.canal}</span>
                      <span>z {n(i.evidencia?.z_recusa)} · recusa {n(i.evidencia?.taxa_recusa_pct)}%</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="vazio">nenhum incidente aberto</p>
            )}
          </div>
        </aside>
      </main>

      <footer className="tira" aria-live="polite">
        <span className="rotulo">alertas (change stream)</span>
        {alertas.length === 0
          ? <span className="vazio">nenhum alerta — abra um incidente</span>
          : alertas.map((a) => (
              <span className="alerta" key={`${a.incident_id}-${a.at}`}>
                <Badge variant="red">{a.incident_id}</Badge>
                {a.provedor_id} · {a.canal} · z {n(a.z_recusa)}
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
