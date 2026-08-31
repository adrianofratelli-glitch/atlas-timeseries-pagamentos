import { useEffect, useMemo, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

// uPlot e não uma biblioteca React de gráfico: a série chega a milhares de pontos e
// redesenha a cada mudança de faixa. React nunca re-renderiza o canvas — só entrega
// dados novos ao ref.

const CORES = {
  entregue: '#0498ec',
  registrado: '#00ed64',
  medido: '#00ed64',
  preenchido: '#ffc010',
}

function fmt(ts) {
  return new Date(ts).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function montarDados(mode, points) {
  const x = points.map((p) => new Date(p.ts).getTime() / 1000)
  if (mode === 'balance') {
    return [x, points.map((p) => p.entregue), points.map((p) => p.registrado)]
  }
  // Ponto reconstruído nunca parece medido: série própria, tracejada, âmbar. Os
  // vizinhos entram nas duas séries para que as linhas se encontrem sem degrau.
  const medido = points.map((p) => (p.filled ? null : p.kwh))
  const preenchido = points.map((p, i) => {
    if (p.filled) return p.kwh
    return points[i - 1]?.filled || points[i + 1]?.filled ? p.kwh : null
  })
  return [x, medido, preenchido]
}

export default function Chart({ mode, points, minHeight = 240, onHover }) {
  const hostRef = useRef(null)
  const plotRef = useRef(null)

  // O callback e os pontos mudam a cada render; guardados em ref, não obrigam a
  // recriar o gráfico — recriar a cada poll de 1,5 s matava o cursor e o zoom.
  const hoverRef = useRef(onHover)
  hoverRef.current = onHover
  const pointsRef = useRef(points)
  pointsRef.current = points

  const dados = useMemo(() => montarDados(mode, points), [mode, points])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return undefined

    const ALTURA_LEGENDA = 34
    const medir = () => ({
      width: host.clientWidth || 800,
      height: Math.max((host.clientHeight || 0) - ALTURA_LEGENDA, minHeight),
    })

    const series = mode === 'balance'
      ? [
        { label: 'instante', value: (u, v) => (v == null ? '—' : fmt(v * 1000)) },
        { label: 'entregue (kWh)', stroke: CORES.entregue, width: 2 },
        { label: 'registrado (kWh)', stroke: CORES.registrado, width: 2 },
      ]
      : [
        { label: 'instante', value: (u, v) => (v == null ? '—' : fmt(v * 1000)) },
        { label: 'medido (kWh)', stroke: CORES.medido, width: 2 },
        { label: 'reconstruído (kWh)', stroke: CORES.preenchido, width: 2, dash: [6, 4] },
      ]

    const opts = {
      ...medir(),
      padding: [12, 12, 0, 0],
      cursor: { drag: { x: true, y: false } },
      legend: { live: true },
      series,
      // A diferença é a banda entre as duas linhas: é o número que interessa, então é
      // a forma que o olho encontra primeiro — não uma terceira linha.
      bands: mode === 'balance' ? [{ series: [1, 2], fill: 'rgba(255, 105, 96, 0.22)' }] : [],
      axes: [
        { stroke: '#889397', grid: { stroke: 'rgba(61,79,88,0.5)' }, ticks: { stroke: '#3d4f58' } },
        { stroke: '#889397', grid: { stroke: 'rgba(61,79,88,0.35)' }, ticks: { stroke: '#3d4f58' } },
      ],
      hooks: {
        // Leitura do instante sob o cursor: a legenda do uPlot fica no rodapé e o
        // apresentador precisa do valor junto das métricas, no alto da tela.
        setCursor: [(u) => {
          const i = u.cursor.idx
          const ponto = i == null ? null : pointsRef.current[i]
          hoverRef.current?.(ponto ? { index: i, ...ponto } : null)
        }],
      },
    }

    plotRef.current = new uPlot(opts, montarDados(mode, pointsRef.current), host)
    const observer = new ResizeObserver(() => plotRef.current?.setSize(medir()))
    observer.observe(host)
    return () => {
      observer.disconnect()
      plotRef.current?.destroy()
      plotRef.current = null
      hoverRef.current?.(null)
    }
  }, [mode, minHeight])

  // Dado novo não recria o gráfico: só troca a série.
  useEffect(() => {
    plotRef.current?.setData(dados)
  }, [dados])

  return <div className="chart-host" ref={hostRef} />
}
