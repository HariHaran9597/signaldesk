import { FormEvent, useEffect, useState } from 'react'
import { ArrowUpRight, Send, X } from 'lucide-react'
import { apiFetch } from './api'
type Topic = 'models' | 'agents' | 'gpu'

export function ManualXCapture() {
  const [enabled, setEnabled] = useState(false)
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [topic, setTopic] = useState<Topic>('models')
  const [createdAt, setCreatedAt] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState(false)
  useEffect(() => { void apiFetch('/api/capabilities').then(response => response.json()).then(value => setEnabled(value.local_x_intake === true)).catch(() => setEnabled(false)) }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(''); setError(false)
    try {
      const payload: { url: string; text: string; topic: Topic; created_at?: string } = { url: url.trim(), text: text.trim(), topic }
      if (createdAt) payload.created_at = new Date(createdAt).toISOString()
      const response = await apiFetch('/api/local-signals/x', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'The post could not be added.')
      setMessage(result.message); setUrl(''); setText(''); setCreatedAt('')
      window.dispatchEvent(new CustomEvent('signaldesk:refresh'))
    } catch (reason) { setError(true); setMessage(reason instanceof Error ? reason.message : 'The post could not be added.') }
    finally { setBusy(false) }
  }

  return <article className="source-card x-capture"><div className="source-card-top"><X size={22}/><span className={`status ${enabled ? 'ok' : ''}`}>{enabled ? 'Local intake ready' : 'Not configured'}</span></div><h2>X signal layer</h2><p>Paste a public post link and its text. Signaldesk stores it for review; the text remains an unverified claim until you check its primary sources.</p>{enabled ? <form className="x-capture-form" onSubmit={submit}><label>Post link<input required type="url" inputMode="url" maxLength={500} placeholder="https://x.com/account/status/…" value={url} onChange={event => setUrl(event.target.value)}/></label><label>Post text<textarea required minLength={10} maxLength={2800} rows={4} placeholder="Paste the exact post text…" value={text} onChange={event => setText(event.target.value)}/></label><div className="x-capture-row"><label>Topic<select value={topic} onChange={event => setTopic(event.target.value as Topic)}><option value="models">Models</option><option value="agents">MCP & agents</option><option value="gpu">GPU & CUDA</option></select></label><label>Post date<input type="datetime-local" value={createdAt} onChange={event => setCreatedAt(event.target.value)}/></label></div><button className="primary wide" type="submit" disabled={busy}><Send size={15}/>{busy ? 'Saving…' : 'Add to evidence queue'}</button>{message && <p className={error ? 'x-capture-message error' : 'x-capture-message'} role={error ? 'alert' : 'status'}>{message}</p>}</form> : <div className="source-footnote">Manual capture is disabled. Automated X login, scraping, and account rotation are not used.</div>}<a className="x-open" href="https://x.com" target="_blank" rel="noopener noreferrer">Open X <ArrowUpRight size={14}/></a></article>
}
