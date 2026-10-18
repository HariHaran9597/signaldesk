import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Check, Clock3, RefreshCw, ShieldCheck } from 'lucide-react'
import { apiFetch } from './api'

type Pipeline = { worker: { state: string; last_seen: string | null }; jobs: { source_id: string; source_name: string; next_due: string; last_success: string | null; last_new_item: string | null; failures: number; state: string; check_overdue: boolean }[]; draft_counts: Record<string, number> }
type Draft = { id: string; status: string; superseded: boolean; evidence: { title: string; excerpt: string; url: string; source_id: string }; output: { headline: string; category: string; limitations: string; claims: { text: string; quote: string; evidence_id: string }[] } | null; issues: string[]; trace: { stage: string; input_tokens?: number; output_tokens?: number; supported?: boolean }[]; model: string; pipeline_version: string; updated_at: string }
type Capabilities = { draft_generation: boolean; draft_provider: string | null; draft_queue?: boolean; public_demo?: boolean }
const labels: Record<string, string> = { awaiting_model: 'Evidence ready', awaiting_evidence: 'Needs more evidence', needs_review: 'Needs human review', held: 'Held by checks', failed: 'Generation stopped', running: 'Preparing', writing: 'Writing draft', reviewing: 'Reviewing draft' }
const time = (value: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'Not yet'

export function PipelineDesk() {
  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState<string | null>(null)
  const [capabilities, setCapabilities] = useState<Capabilities>({ draft_generation: false, draft_provider: null })
  const [runBusy, setRunBusy] = useState(false)
  const [runMessage, setRunMessage] = useState('')
  const [runError, setRunError] = useState(false)
  const detailPanel = useRef<HTMLDivElement>(null)
  useEffect(() => { if (selected) detailPanel.current?.scrollIntoView({ block: 'start', behavior: 'instant' }) }, [selected])
  async function refresh() {
    setBusy(true)
    try {
      const responses = await Promise.all([apiFetch('/api/pipeline'), apiFetch('/api/drafts'), apiFetch('/api/capabilities')])
      if (responses.some(response => !response.ok)) throw new Error('Unavailable')
      const [health, queue, caps] = await Promise.all(responses.map(response => response.json()))
      setPipeline(health); setDrafts(queue.drafts); setCapabilities(caps); setError(false)
    } catch { setError(true) } finally { setBusy(false) }
  }
  async function generateDraft() {
    setRunBusy(true); setRunMessage(''); setRunError(false)
    try {
      const response = await apiFetch('/api/drafts/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: 1 }) })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'The draft could not be started.')
      setRunMessage(result.message || 'Draft generation started. Refresh the queue to follow progress.')
      void refresh()
    } catch (reason) { setRunError(true); setRunMessage(reason instanceof Error ? reason.message : 'The draft could not be started.') }
    finally { setRunBusy(false) }
  }
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { void refresh() }, 30000); return () => window.clearInterval(timer) }, [])
  const visible = drafts.filter(draft => filter === 'all' || draft.status === filter)
  const detail = drafts.find(draft => draft.id === selected)
  return <section className="pipeline-desk">
    <div className="feed-heading"><h2>Behind each briefing</h2><button className="secondary compact" onClick={() => void refresh()} disabled={busy}><RefreshCw size={14}/>{busy ? 'Checking…' : 'Refresh'}</button></div>
    <p className="pipeline-intro">Follow the evidence from collection to review. Drafts stay here until a human has checked them. Publishing is not enabled in this build.</p>
    {error && <p role="alert" className="pipeline-alert">The workflow service is unavailable. Any status below is from the previous check.</p>}
    {pipeline && <>
      <div className="pipeline-stats"><div><Clock3 size={17}/><strong>{pipeline.worker.state === 'recent_heartbeat' ? 'Worker recently seen' : 'Worker not observed'}</strong><small>Last heartbeat {time(pipeline.worker.last_seen)}</small></div><div><ShieldCheck size={17}/><strong>{capabilities.public_demo ? 'Private queue' : `${Object.values(pipeline.draft_counts).reduce((sum, value) => sum + value, 0)} evidence packets`}</strong><small>{capabilities.public_demo ? 'Not included in this snapshot' : 'No drafts are automatically published'}</small></div></div>
      <div className="job-list">{pipeline.jobs.map(job => <article className="job-row" key={job.source_id}><div><strong>{job.source_name}</strong><span className={job.failures || job.check_overdue ? 'job-state warn' : 'job-state'}>{job.check_overdue ? 'Check overdue' : job.state.replace('_', ' ')}</span></div><dl><div><dt>Last successful check</dt><dd>{time(job.last_success)}</dd></div><div><dt>Last new item found</dt><dd>{time(job.last_new_item)}</dd></div><div><dt>Next attempt</dt><dd>{time(job.next_due)}</dd></div></dl>{job.failures > 0 && <p>{job.failures} consecutive failed attempts; retries are spaced out.</p>}</article>)}</div>
      {!pipeline.jobs.length && <p className="source-explainer">No collection schedule has been initialized yet.</p>}
    </>}
    <div className="feed-heading"><h2>{capabilities.public_demo ? 'Private review workspace' : 'Evidence queue'} {!capabilities.public_demo && <span>{visible.length}</span>}</h2><span className="sort-label">{capabilities.public_demo ? 'Hidden from the public snapshot' : 'Human review required'}</span></div>
    {capabilities.public_demo ? <div className="empty"><h3>Drafts stay private</h3><p>The public demo includes source and model metadata only. Generated text, evidence packets, and model traces remain in the local workspace.</p></div> : <>
    {capabilities.draft_generation && <div className="draft-run-control"><div><strong>Turn the next signal into a draft</strong><p>{capabilities.draft_provider === 'experiential' ? 'Uses the configured free-only model. One story, at most two model calls, no paid fallback.' : 'Uses the local model configured on this machine. One story per run.'} Every result stays unpublished for human review.</p>{runMessage && <p className={runError ? 'x-capture-message error' : 'x-capture-message'} role={runError ? 'alert' : 'status'}>{runMessage}</p>}</div><button className="primary" onClick={() => void generateDraft()} disabled={runBusy || busy}>{runBusy ? 'Starting…' : 'Generate one draft'}</button></div>}
    <div className="filters"><button className={`chip ${filter === 'all' ? 'selected' : ''}`} onClick={() => setFilter('all')}>All packets</button>{['needs_review', 'held', 'awaiting_model', 'awaiting_evidence', 'failed'].map(status => <button key={status} className={`chip ${filter === status ? 'selected' : ''}`} onClick={() => setFilter(status)}>{labels[status]}</button>)}</div>
    {!visible.length && <div className="empty"><h3>{busy ? 'Loading evidence…' : 'No packets in this view'}</h3><p>Collected evidence will appear here after draft preparation.</p></div>}
    <div className="draft-list">{visible.map(draft => <button className={`draft-row ${selected === draft.id ? 'selected' : ''}`} key={draft.id} onClick={() => setSelected(selected === draft.id ? null : draft.id)} aria-expanded={selected === draft.id}><div><span className={`draft-status ${draft.status}`}>{labels[draft.status] || draft.status}{draft.superseded ? ' · source changed' : ''}</span><small>{draft.evidence.source_id}</small></div><h3>{draft.output?.headline || draft.evidence.title}</h3><p>{draft.issues[0] || 'Draft and model review complete. A human still needs to check the claims.'}</p><span className="draft-open">{selected === draft.id ? 'Close evidence' : 'Inspect evidence'} <ArrowUpRight size={14}/></span></button>)}</div>
    {detail && <article ref={detailPanel} className="draft-detail" aria-label="Draft evidence detail"><div className="hero-label"><ShieldCheck size={17}/> EVIDENCE & REVIEW</div><h2>{detail.output?.headline || detail.evidence.title}</h2><p className="source-explainer">{labels[detail.status] || detail.status} · {detail.model === 'none' ? 'No model used' : detail.model} · Updated {time(detail.updated_at)}</p>{detail.superseded && <p className="pipeline-alert">The source changed after this packet was created. This evidence is an older version.</p>}<div className="evidence-box"><span>ORIGINAL PUBLISHER EXCERPT</span><p>{detail.evidence.excerpt || 'No excerpt supplied. More source material is needed.'}</p></div>{detail.output?.claims.map((claim, index) => <div className="claim" key={index}><strong>Draft claim {index + 1}</strong><p>{claim.text}</p><blockquote>{claim.quote}</blockquote><small>Reference: {claim.evidence_id.slice(0, 12)}…</small></div>)}{detail.output && <p className="detail-disclaimer">Limitations: {detail.output.limitations}</p>}{detail.issues.length > 0 && <ul className="review-issues">{detail.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}<div className="trace">{detail.trace.map((step, index) => <span key={index}><Check size={12}/>{step.stage}{step.output_tokens !== undefined ? ` · ${step.output_tokens} tokens` : ''}</span>)}</div><p className="detail-disclaimer">Citation matching only checks that the quoted text exists. A model review is not independent verification. Every generated draft still requires human review.</p><a className="secondary" href={detail.evidence.url.startsWith('https://') ? detail.evidence.url : '#'} target="_blank" rel="noopener noreferrer">Read the publisher <ArrowUpRight size={15}/></a></article>}
    </>}
  </section>
}
