const BASE = import.meta.env.VITE_API ?? 'http://127.0.0.1:8400'

async function get(path, params) {
  const url = new URL(BASE + path)
  Object.entries(params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null) url.searchParams.set(k, v)
  })
  const res = await fetch(url)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(body?.detail?.reason ?? res.statusText), { status: res.status, body })
  return body
}

async function post(path, payload) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: payload ? JSON.stringify(payload) : undefined,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(body?.detail?.reason ?? res.statusText), { status: res.status, body })
  return body
}

export const api = {
  base: BASE,
  health: () => get('/health'),
  transformers: () => get('/api/transformers'),
  meters: (id) => get(`/api/transformers/${id}/meters`),
  scenarios: () => get('/api/scenarios'),
  curve: (meterId, days, fill) => get('/api/curve', { meter_id: meterId, days, fill }),
  balance: (transformerId, days) => get('/api/balance', { transformer_id: transformerId, days }),
  storage: () => get('/api/storage'),
  cases: () => get('/api/cases'),
  openCase: (payload) => post('/api/cases', payload),
  reset: () => post('/api/demo/reset'),
  stream: () => new EventSource(`${BASE}/api/alerts/stream`),
}
