import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, BookmarkPlus, RefreshCw, Scale, Search, Sparkles } from 'lucide-react'
import { apiFetch } from './api'

type Model = { id: string; author: string | null; name: string; description: string; url: string; license: string | null; downloads: number; likes: number; pipeline_tag: string | null; last_modified: string | null; trend_rank: number; download_change_24h: number | null; download_change_7d: number | null }
type Response = { models: Model[]; updated_at: string | null; method: string }
const number = (value: number) => new Intl.NumberFormat(undefined, { notation: value > 999_999 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value)
const date = (value: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value)) : 'Not supplied'

export function ModelLab() {
  const [models, setModels] = useState<Model[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [updated, setUpdated] = useState<string | null>(null)
  const [method, setMethod] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  async function refresh() {
    setLoading(true); setError('')
    try {
      const response = await apiFetch('/api/models')
      if (!response.ok) throw new Error('unavailable')
      const result: Response = await response.json()
      setModels(result.models); setUpdated(result.updated_at); setMethod(result.method)
    } catch { setError('Model discovery is waiting for the next successful Hugging Face collection.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void refresh() }, [])
  const visible = useMemo(() => models.filter(model => `${model.id} ${model.description}`.toLowerCase().includes(query.toLowerCase())), [models, query])
  const compare = models.filter(model => selected.includes(model.id))
  function toggle(id: string) { setSelected(current => current.includes(id) ? current.filter(value => value !== id) : current.length < 3 ? [...current, id] : current) }
  return <section className="model-lab">
    <div className="model-lab-head"><div><div className="hero-label"><Sparkles size={14}/> DISCOVERY, WITH CONTEXT</div><h2>Model radar<span>.</span></h2><p>Track what the Hugging Face community is exploring, then compare basic model-card metadata side by side.</p></div><button className="secondary compact" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14}/>{loading ? 'Updating…' : 'Refresh'}</button></div>
    <div className="model-method"><span className="note-badge">POPULARITY IS NOT QUALITY</span><p>{method || 'Hugging Face download growth is a discovery signal, not a quality ranking.'} {updated ? `Last collected ${date(updated)}.` : ''} Historical growth appears after repeat hourly collections.</p></div>
    {error && <p className="pipeline-alert" role="status">{error}</p>}
    <div className="model-tools"><label className="model-search"><Search size={15}/><input aria-label="Search discovered models" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search model cards"/></label><span>{selected.length}/3 selected</span></div>
    {!loading && !models.length && <div className="empty"><h3>No model snapshots yet</h3><p>The hourly collector will populate this page after the first successful API check.</p></div>}
    <div className="model-grid">{visible.map(model => <article key={model.id} className={`model-card ${selected.includes(model.id) ? 'chosen' : ''}`}><div className="model-card-top"><span className="model-rank">{model.download_change_24h === null ? `#${model.trend_rank} BY DOWNLOADS` : `${model.download_change_24h >= 0 ? '+' : ''}${number(model.download_change_24h)} / 24H`}</span><button className={`model-pick ${selected.includes(model.id) ? 'picked' : ''}`} onClick={() => toggle(model.id)} aria-pressed={selected.includes(model.id)} aria-label={`${selected.includes(model.id) ? 'Remove' : 'Compare'} ${model.id}`}><Scale size={15}/>{selected.includes(model.id) ? 'Selected' : 'Compare'}</button></div><h3>{model.id}</h3><p className="model-description">{model.description || 'Open the model card for its description and documentation.'}</p><div className="model-metrics"><div><strong>{number(model.downloads)}</strong><small>downloads</small></div><div><strong>{number(model.likes)}</strong><small>likes</small></div><div><strong>{model.download_change_7d === null ? 'Building' : `${model.download_change_7d >= 0 ? '+' : ''}${number(model.download_change_7d)}`}</strong><small>downloads / 7d</small></div></div><div className="model-meta"><span>{model.pipeline_tag || 'Task not supplied'}</span><span>{model.license || 'License not supplied'}</span><span>Updated {date(model.last_modified)}</span></div><a href={model.url} target="_blank" rel="noopener noreferrer">Open model card <ArrowUpRight size={14}/></a></article>)}</div>
    {compare.length > 0 && <section className="comparison"><div className="feed-heading"><h2>Side by side <span>{compare.length}</span></h2><button className="secondary compact" onClick={() => setSelected([])}><BookmarkPlus size={14}/>Clear picks</button></div><p className="source-explainer">This view compares public model-card metadata and observed download changes. It does not rank capability or substitute for matched benchmarks.</p><div className="compare-table-wrap"><table className="compare-table"><thead><tr><th>Signal</th>{compare.map(model => <th key={model.id}>{model.id}</th>)}</tr></thead><tbody><tr><th>Task</th>{compare.map(model => <td key={model.id}>{model.pipeline_tag || 'Not supplied'}</td>)}</tr><tr><th>License</th>{compare.map(model => <td key={model.id}>{model.license || 'Not supplied'}</td>)}</tr><tr><th>Downloads</th>{compare.map(model => <td key={model.id}>{number(model.downloads)}</td>)}</tr><tr><th>Downloads / 24h</th>{compare.map(model => <td key={model.id}>{model.download_change_24h === null ? 'Baseline building' : `${model.download_change_24h >= 0 ? '+' : ''}${number(model.download_change_24h)}`}</td>)}</tr><tr><th>Downloads / 7d</th>{compare.map(model => <td key={model.id}>{model.download_change_7d === null ? 'Baseline building' : `${model.download_change_7d >= 0 ? '+' : ''}${number(model.download_change_7d)}`}</td>)}</tr><tr><th>Likes</th>{compare.map(model => <td key={model.id}>{number(model.likes)}</td>)}</tr><tr><th>Last updated</th>{compare.map(model => <td key={model.id}>{date(model.last_modified)}</td>)}</tr></tbody></table></div></section>}
  </section>
}
