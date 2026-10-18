type Snapshot = {
  generated_at: string
  items: unknown[]
  sources: unknown[]
  models: unknown[]
  pipeline: unknown
  capabilities: Record<string, unknown>
}

export const isPublicDemo = import.meta.env.VITE_DEMO_MODE === 'true'
let snapshotPromise: Promise<Snapshot> | undefined

function loadSnapshot(): Promise<Snapshot> {
  snapshotPromise ??= fetch(`${import.meta.env.BASE_URL}demo-data.json`).then(async response => {
    if (!response.ok) throw new Error('The public demo snapshot is unavailable.')
    return response.json() as Promise<Snapshot>
  })
  return snapshotPromise
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  if (!isPublicDemo) return fetch(path, init)
  if (init?.method && init.method.toUpperCase() !== 'GET') {
    return new Response(JSON.stringify({ detail: 'The public demo is read-only.' }), { status: 404, headers: { 'Content-Type': 'application/json' } })
  }
  const snapshot = await loadSnapshot()
  const route = new URL(path, window.location.origin).pathname.split('/').filter(Boolean).at(-1)
  const body = route === 'items' ? { items: snapshot.items, generated_at: snapshot.generated_at }
    : route === 'sources' ? { sources: snapshot.sources, connectors: { x: 'not configured', inference: 'not exposed in public demo' }, generated_at: snapshot.generated_at }
        : route === 'models' ? { models: snapshot.models, updated_at: snapshot.generated_at, method: 'Six-hour public metadata snapshots. Download changes are a discovery signal, not a quality ranking; 24-hour and 7-day baselines build over time.' }
        : route === 'pipeline' ? snapshot.pipeline
          : route === 'drafts' ? { drafts: [], publication_enabled: false }
            : route === 'capabilities' ? snapshot.capabilities
              : { detail: 'This endpoint is not available in the public demo.' }
  const status = route && ['items', 'sources', 'models', 'pipeline', 'drafts', 'capabilities'].includes(route) ? 200 : 404
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
