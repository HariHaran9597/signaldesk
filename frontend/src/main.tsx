import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowDown, ArrowRight, ArrowUpRight, Bookmark, Check, CheckCircle2, Cpu, Layers3, Radio, Search, Settings2, Sparkles, X, Zap } from 'lucide-react'
import './style.css'
import { PipelineDesk } from './PipelineDesk'
import { ModelLab } from './ModelLab'
import { ManualXCapture } from './ManualXCapture'
import { apiFetch, isPublicDemo } from './api'

type Topic = 'models' | 'agents' | 'gpu'
type Item = { id: string; source_id: string; topic: Topic; title: string; url: string; excerpt: string; published_at: string | null; fetched_at: string; evidence_status: string; editorial_status: string }
type Source = { id: string; name: string; topic: Topic; website: string; status: string; checked_at: string | null; newest_observed: string | null; count: number; error: string | null }
const topics: Record<Topic, { label: string; description: string; icon: typeof Cpu }> = {
  models: { label: 'Models', description: 'Releases, research & open weights', icon: Sparkles },
  agents: { label: 'MCP & agents', description: 'Protocols, tools & integrations', icon: Layers3 },
  gpu: { label: 'GPU & CUDA', description: 'Compute, kernels & local inference', icon: Cpu },
}
const allTopics = Object.keys(topics) as Topic[]

function loadArray(key: string): string[] {
  try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [] } catch { return [] }
}
function saveArray(key: string, value: string[]) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* Browser storage may be disabled. */ }
}
function date(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value)) : 'Date not supplied'
}
function safeUrl(value: string) {
  try { const parsed = new URL(value); return parsed.protocol === 'https:' && !parsed.username && !parsed.password ? parsed.href : '#' } catch { return '#' }
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close() }, [])
  return <dialog ref={dialog} onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose() }}><div className="modal-head"><span>{title}</span><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20}/></button></div>{children}</dialog>
}

function App() {
  const [items, setItems] = useState<Item[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('feed')
  const [topic, setTopic] = useState<Topic | 'all'>('all')
  const [query, setQuery] = useState('')
  const [saved, setSaved] = useState(() => loadArray('signaldesk:saved'))
  const [interests, setInterests] = useState<Topic[]>(() => loadArray('signaldesk:interests').filter((value): value is Topic => allTopics.includes(value as Topic)))
  const [preferences, setPreferences] = useState(false)
  const [selected, setSelected] = useState<Item | null>(null)
  const [snapshotUpdated, setSnapshotUpdated] = useState<string | null>(null)

  async function refresh() {
    setLoading(true); setError('')
    try {
      const responses = await Promise.all([apiFetch('/api/items?limit=120'), apiFetch('/api/sources')])
      if (responses.some(response => !response.ok)) throw new Error('The reading desk could not reach its source service.')
      const [feed, health] = await Promise.all(responses.map(response => response.json()))
      setItems(feed.items); setSources(health.sources); setSnapshotUpdated(feed.generated_at || null)
    } catch { setError('The source service is unavailable. Start the API, then try again. Your saved preferences are still on this device.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void refresh() }, [])
  useEffect(() => { const handler = () => { void refresh() }; window.addEventListener('signaldesk:refresh', handler); return () => window.removeEventListener('signaldesk:refresh', handler) }, [])
  useEffect(() => { saveArray('signaldesk:saved', saved) }, [saved])
  useEffect(() => { saveArray('signaldesk:interests', interests) }, [interests])
  const toggleSaved = (id: string) => setSaved(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])
  const toggleInterest = (value: Topic) => setInterests(current => current.includes(value) ? current.filter(item => item !== value) : [...current, value])
  const visible = items.filter(item => (tab !== 'saved' || saved.includes(item.id)) && (topic === 'all' || item.topic === topic) && (!query || `${item.title} ${item.excerpt}`.toLowerCase().includes(query.toLowerCase()))).sort((a, b) => Number(interests.includes(b.topic)) - Number(interests.includes(a.topic)) || (b.published_at || '').localeCompare(a.published_at || ''))
  const sourceName = (id: string) => sources.find(source => source.id === id)?.name || id

  return <div className="shell">
    <aside className="sidebar">
      <a href="#" className="brand" onClick={event => { event.preventDefault(); setTab('feed') }}><span className="brand-mark"><Radio size={21}/></span>signaldesk<span className="brand-dot">.</span></a>
      <div className="workspace-label">YOUR READING ROOM <span>01</span></div>
      <nav aria-label="Main navigation">
        <button className={tab === 'feed' ? 'nav-item active' : 'nav-item'} onClick={() => setTab('feed')}><Zap size={18}/>For you<span className="nav-dot"/></button>
        <button className={tab === 'saved' ? 'nav-item active' : 'nav-item'} onClick={() => setTab('saved')}><Bookmark size={18}/>Saved<span className="count">{saved.length}</span></button>
        <button className={tab === 'models' ? 'nav-item active' : 'nav-item'} onClick={() => setTab('models')}><Cpu size={18}/>Model radar</button>
        <button className={tab === 'sources' ? 'nav-item active' : 'nav-item'} onClick={() => setTab('sources')}><Radio size={18}/>Source desk</button>
      </nav>
      <div className="section-label">YOUR FREQUENCIES</div>
      <div className="interest-list">{allTopics.map(key => { const Icon = topics[key].icon; return <button key={key} onClick={() => toggleInterest(key)} className={interests.includes(key) ? 'interest selected' : 'interest'} aria-pressed={interests.includes(key)}><Icon size={16}/>{topics[key].label}<span>{interests.includes(key) ? <Check size={14}/> : '+'}</span></button> })}</div>
      <button className="tune-link" onClick={() => setPreferences(true)}><Settings2 size={15}/>Tune your feed</button>
      <div className="sidebar-bottom"><div className="small-orbit"/><p>A little less noise.<br/><strong>A lot more context.</strong></p><div className="version">BUILD 0.1 <span>SOURCE PREVIEW</span></div></div>
    </aside>
    <main>
      <header className="topbar"><div className="breadcrumb">Your space <span>/</span> {tab === 'sources' ? 'Source desk' : tab === 'saved' ? 'Saved' : tab === 'models' ? 'Model radar' : 'For you'}</div><label className="search"><Search size={16}/><input aria-label="Search updates" placeholder="Find a signal…" value={query} onChange={event => setQuery(event.target.value)}/></label><button className="avatar" aria-label="Edit your interests" onClick={() => setPreferences(true)}>You</button></header>
      <div className="main-content">
        <div className="eyebrow"><span className="pulse"/> A PERSONAL LENS ON AI <span className="edition">{isPublicDemo ? `READ-ONLY SNAPSHOT · UPDATED ${date(snapshotUpdated).toUpperCase()}` : 'EARLY BUILD / 001'}</span></div>
        <div className="title-row"><h1>{tab === 'saved' ? <>Worth coming<br/>back to<span>.</span></> : tab === 'sources' ? <>Good signals start<br/>at the source<span>.</span></> : tab === 'models' ? <>Compare the<br/>signals<span>.</span></> : <>Your AI world.<br/><span className="muted-title">In focus.</span></>}</h1><p>{tab === 'sources' ? 'See what was checked, what came back, and where coverage still needs work.' : tab === 'models' ? 'Explore current model activity and compare the details that are actually published.' : 'Models, tools, and the ideas behind them. A reading desk tuned to what you care about.'}</p></div>
        {tab === 'feed' && <section className="hero"><div className="hero-copy"><div className="hero-label"><Sparkles size={14}/> MAKE IT YOURS</div><h2>Follow your curiosity.<br/>Find your next <em>signal.</em></h2><p>Pick your interests. Relevant source updates rise to the top. The original context stays one tap away.</p><button className="primary" onClick={() => setPreferences(true)}>Tune my feed <ArrowUpRight size={17}/></button></div><div className="hero-art" aria-hidden="true"><div className="orbit one"/><div className="orbit two"/><div className="orbit three"/><div className="orb-core"><Radio size={44}/></div><span className="floating-tag tag-model">MODELS <Sparkles size={12}/></span><span className="floating-tag tag-agent">AGENTS <Layers3 size={12}/></span><span className="floating-tag tag-compute">COMPUTE <Cpu size={12}/></span><div className="cross cross-a">+</div><div className="cross cross-b">+</div><span className="art-caption">CONNECT THE DOTS. KEEP THE CONTEXT.</span></div></section>}
        {tab !== 'models' && <div className="preview-note"><span className="note-badge">TRANSPARENT BY DESIGN</span><p>These are publisher excerpts. Generated drafts stay in the Source desk for review. Add X posts manually there; automated collection is not connected.</p></div>}
        {tab === 'models' && <ModelLab/>}
        {tab === 'sources' && <PipelineDesk/>}
        {error && <div className="empty" role="alert"><h3>Connection paused</h3><p>{error}</p><button className="secondary" onClick={() => void refresh()}>Try again</button></div>}
        {!error && tab === 'sources' && <section className="source-grid">{sources.filter(source => source.id !== 'x-manual').map(source => <article className="source-card" key={source.id}><div className="source-card-top"><Radio size={22}/><span className={`status ${source.status}`}>{source.status === 'ok' ? 'Fetch succeeded' : source.status === 'error' ? 'Fetch failed' : 'Not checked'}</span></div><h2>{source.name}</h2><p>{topics[source.topic].description}</p><dl><div><dt>Items stored</dt><dd>{source.count}</dd></div><div><dt>Last checked</dt><dd>{date(source.checked_at)}</dd></div><div><dt>Newest observed</dt><dd>{date(source.newest_observed)}</dd></div></dl><a href={safeUrl(source.website)} target="_blank" rel="noopener noreferrer">Visit original source <ArrowUpRight size={15}/></a></article>)}<ManualXCapture/><p className="source-explainer">Fetch status reports transport and parsing success. Newest observed is the latest date in the response; neither proves complete account coverage.</p></section>}
        {!error && tab !== 'sources' && <>
          <div className="feed-heading"><h2>{tab === 'saved' ? 'Your collection' : 'On your radar'} <span>{visible.length}</span></h2><span className="sort-label">{interests.length ? 'Your interests first' : 'Newest first'} <ArrowDown size={13}/></span></div>
          <div className="filters" aria-label="Filter by topic"><button onClick={() => setTopic('all')} className={topic === 'all' ? 'chip selected' : 'chip'}>All signals</button>{allTopics.map(key => <button key={key} onClick={() => setTopic(key)} className={topic === key ? 'chip selected' : 'chip'}>{topics[key].label}</button>)}</div>
          {loading ? <div className="empty" role="status">Loading your reading desk…</div> : visible.length === 0 ? <div className="empty"><Radio size={28}/><h3>{tab === 'saved' ? 'Room for your next discovery' : 'No signals here yet'}</h3><p>{tab === 'saved' ? 'Save an update from your feed and it will appear here.' : 'Change the filters, or run source collection to populate this desk.'}</p></div> : <div className="card-grid">{visible.map((item, index) => { const Icon = topics[item.topic].icon; return <article className={`story-card ${item.topic}`} key={item.id}><button className="card-art" onClick={() => setSelected(item)} aria-label={`Read ${item.title}`}><div className="art-grid"/><span className="art-kicker">{topics[item.topic].label.toUpperCase()}</span><Icon className="art-symbol" size={58} strokeWidth={1}/><span className="art-number">{String(index + 1).padStart(2, '0')}</span><span className="art-bottom">{sourceName(item.source_id)} <ArrowUpRight size={17}/></span></button><div className="card-body"><div className="card-meta"><span>{sourceName(item.source_id)}</span><span>{date(item.published_at)}</span></div><button className="story-title" onClick={() => setSelected(item)}><h3>{item.title}</h3></button><p className="excerpt">{item.excerpt || 'Open the original source for the full announcement.'}</p><div className="relevance">{interests.includes(item.topic) ? <><Sparkles size={12}/>Matches your {topics[item.topic].label.toLowerCase()} interest</> : <><Radio size={12}/>From a tracked publisher</>}</div><div className="card-footer"><span className="evidence-label">Source excerpt · unreviewed</span><button className={saved.includes(item.id) ? 'save saved' : 'save'} aria-label={`${saved.includes(item.id) ? 'Unsave' : 'Save'} ${item.title}`} aria-pressed={saved.includes(item.id)} onClick={() => toggleSaved(item.id)}><Bookmark size={17} fill={saved.includes(item.id) ? 'currentColor' : 'none'}/></button></div></div></article> })}</div>}
          {!loading && visible.length > 0 && <div className="caught-up"><CheckCircle2 size={22}/><h3>That’s your current signal.</h3><p>Check the Source desk for collection schedules, freshness, and draft reviews.</p></div>}
        </>}
        <footer><span>signaldesk. <span className="footer-muted">Built for curiosity, with context.</span></span><button onClick={() => setTab('sources')}>Inspect our sources <ArrowRight size={13}/></button></footer>
      </div>
    </main>
    {preferences && <Modal title="TUNE YOUR FREQUENCIES" onClose={() => setPreferences(false)}><h2>A feed that feels<br/>like <em>you.</em></h2><p className="modal-intro">Choose what you follow. We’ll put those updates first, while leaving room to explore.</p><div className="preference-options">{allTopics.map(key => { const Icon = topics[key].icon; return <button key={key} className={interests.includes(key) ? 'preference active' : 'preference'} onClick={() => toggleInterest(key)} aria-pressed={interests.includes(key)}><Icon size={23}/><span><strong>{topics[key].label}</strong><small>{topics[key].description}</small></span><span className="checkbox">{interests.includes(key) && <Check size={15}/>}</span></button> })}</div><div className="local-note">Preferences and saves stay in this browser. Account sync is planned.</div><button className="primary wide" onClick={() => setPreferences(false)}>Find my signals <ArrowRight size={17}/></button></Modal>}
    {selected && <Modal title="THE SOURCE, IN CONTEXT" onClose={() => setSelected(null)}><div className="detail-topic">{topics[selected.topic].label} / {sourceName(selected.source_id)}</div><h2 className="detail-title">{selected.title}</h2><div className="detail-date">Published {date(selected.published_at)} · Collected {date(selected.fetched_at)}</div><div className="evidence-box"><span>STORED SOURCE EXCERPT</span><p>{selected.excerpt || 'The publisher did not provide an excerpt.'}</p></div><p className="detail-disclaimer">This excerpt has not been independently verified or reviewed by an editor. Source claims are not conclusions from Signaldesk. Follow the original link for complete context.</p><a className="primary wide" href={safeUrl(selected.url)} target="_blank" rel="noopener noreferrer">Read original source <ArrowUpRight size={17}/></a><button className="secondary wide" onClick={() => toggleSaved(selected.id)}>{saved.includes(selected.id) ? 'Remove from saved' : 'Save for later'}<Bookmark size={16}/></button></Modal>}
  </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>)
