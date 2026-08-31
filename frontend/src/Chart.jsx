import { useEffect, useRef } from 'react'
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
  return new Date(ts).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export default function Chart({ mode, points, minHeight = 240 }) {
  const hostRef = useRef(null)
  const plotRef = useRef(null)

  useEffect(() => {
    if (!hostRef.current) return
    const host = hostRef.current
    const x = points.map((p) => new Date(p.ts).getTime() / 1000)

    let series
    let data
    let bands
    if (mode === 'balance') {
      data = [x, points.map((p) => p.entregue), points.map((p) => p.registrado)]
      series = [
        { label: 'instante', value: (u, v) => (v == null ? '—' : fmt(v * 1000)) },
        { label: 'entregue (kWh)', stroke: CORES.entregue, width: 2 },
        { label: 'registrado (kWh)', stroke: CORES.registrado, width: 2 },
      ]
      // A diferença é a banda entre as duas linhas: é o número que interessa, então
      // é a forma que o olho encontra primeiro — não uma terceira linha.
      bands = [{ series: [1, 2], fill: 'rgba(255, 105, 96, 0.22)' }]
    } else {
      // Ponto reconstruído nunca parece medido: série própria, tracejada, âmbar.
      const medido = points.map((p) => (p.filled ? null : p.kwh))
      const preenchido = points.map((p, i) => {
        if (p.filled) return p.kwh
        const antes = points[i - 1]
        const depois = points[i + 1]
        return antes?.filled || depois?.filled ? p.kwh : null
      })
      data = [x, medido, preenchido]
      series = [
        { label: 'instante', value: (u, v) => (v == null ? '—' : fmt(v * 1000)) },
        { label: 'medido (kWh)', stroke: CORES.medido, width: 2 },
        { label: 'reconstruído (kWh)', stroke: CORES.preenchido, width: 2, dash: [6, 4] },
      ]
      bands = []
    }

    // A altura vem do contêiner, não de uma constante: com altura fixa sobrava meia
    // tela vazia embaixo do gráfico em 1600×1000.
    // A legenda do uPlot é irmã do canvas dentro do mesmo host: sem descontar a
    // altura dela, ela some atrás da gaveta de query.
    const ALTURA_LEGENDA = 34
    const medir = () => ({
      width: host.clientWidth || 800,
      height: Math.max((host.clientHeight || 0) - ALTURA_LEGENDA, minHeight),
    })
    const tamanho = medir()

    const opts = {
      ...tamanho,
      padding: [12, 12, 0, 0],
      cursor: { drag: { x: true, y: false } },
      legend: { live: true },
      series,
      bands,
      axes: [
        { stroke: '#889397', grid: { stroke: 'rgba(61,79,88,0.5)' }, ticks: { stroke: '#3d4f58' } },
        { stroke: '#889397', grid: { stroke: 'rgba(61,79,88,0.35)' }, ticks: { stroke: '#3d4f58' } },
      ],
    }

    plotRef.current = new uPlot(opts, data, host)
    const observer = new ResizeObserver(() => plotRef.current?.setSize(medir()))
    observer.observe(host)
    return () => {
      observer.disconnect()
      plotRef.current?.destroy()
      plotRef.current = null
    }
  }, [mode, points, minHeight])

  return <div className="chart-host" ref={hostRef} />
}
