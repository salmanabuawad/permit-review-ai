import { useEffect, useState } from 'react'
import { api, fmtDate, uploadWithProgress } from '../api'
import { useApp } from '../App'

const TEXT_HE: Record<string, string> = { ok: 'טקסט חולץ', empty: 'ללא טקסט (סרוק?)', failed: 'חילוץ נכשל', none: '—' }
const IMPORT_HE: Record<string, string> = { queued: 'ממתין', running: 'בעיבוד', done: 'הסתיים', failed: 'נכשל' }
const mb = (n: number) => n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`

/** Superadmin: the knowledge base the AI assistant answers from — national documents (laws, regulations,
 *  procedures; searched for every committee) and committee documents. Text is extracted on upload; splitting and
 *  embedding run in the background worker, and the table shows the progress. */
export default function Knowledge() {
  const { toast } = useApp()
  const [rows, setRows] = useState<any[] | null>(null), [kinds, setKinds] = useState<Record<string, string>>({})
  const [scope, setScope] = useState('national'), [q, setQ] = useState(''), [dir, setDir] = useState<any[]>([])
  const [kind, setKind] = useState('regulation'), [title, setTitle] = useState(''), [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false), [log, setLog] = useState<string[]>([]), [filter, setFilter] = useState('')
  const [imports, setImports] = useState<any[]>([]), [pct, setPct] = useState<number | null>(null)
  const loadImports = () => api.get<any>('/api/knowledge/imports').then(x => setImports(x.rows)).catch(() => {})
  useEffect(() => { loadImports() }, [])
  useEffect(() => {                                    // a ZIP import runs in the background: follow it
    if (!imports.some(j => j.status === 'queued' || j.status === 'running')) return
    const t = setTimeout(() => { loadImports(); load() }, 5000)
    return () => clearTimeout(t)
  }, [imports])
  const load = () => api.get<any>(`/api/knowledge/uploads${filter ? `?scope=${encodeURIComponent(filter)}` : ''}`)
    .then(x => { setRows(x.rows); setKinds(x.kinds) }).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [filter])
  useEffect(() => {                                    // indexing runs in the background: refresh while unfinished
    if (!rows?.some(r => r.status === 'ok' && r.text_status === 'ok' && r.embedded < Math.max(r.chunks, 1))) return
    const t = setTimeout(load, 15000)
    return () => clearTimeout(t)
  }, [rows])
  useEffect(() => {
    const t = setTimeout(() => api.get<any[]>(`/api/committees/directory?q=${encodeURIComponent(q)}`).then(setDir).catch(() => setDir([])), 250)
    return () => clearTimeout(t)
  }, [q])

  const upload = async () => {
    setBusy(true); setLog([])
    for (const f of files) {
      if (f.name.toLowerCase().endsWith('.zip')) {    // archive: streamed to the server, documents added in the background
        const fd = new FormData()
        fd.append('scope', scope); fd.append('kind', kind); fd.append('file', f)
        try {
          setPct(0)
          const j = await uploadWithProgress<any>('/api/knowledge/imports', fd, setPct)
          setLog(l => [...l, `${f.name}: הארכיון התקבל — ${j.total} קבצים, נוספים ברקע`])
        } catch (e: any) { setLog(l => [...l, `${f.name}: ${e.message}`]) }
        setPct(null); loadImports()
        continue
      }
      const fd = new FormData()
      fd.append('file', f); fd.append('scope', scope); fd.append('kind', kind); fd.append('title', files.length === 1 ? title : '')
      try { const r = await api.upload<any>('/api/knowledge/uploads', fd); setLog(l => [...l, `${f.name}: ${TEXT_HE[r.text_status] ?? r.text_status} · ${r.pages} עמ׳`]) }
      catch (e: any) { setLog(l => [...l, `${f.name}: ${e.message}`]) }
    }
    setFiles([]); setTitle('')
    const el = document.getElementById('kb-files') as HTMLInputElement | null
    if (el) el.value = ''
    setBusy(false); load()
  }
  const retire = async (r: any) => {
    if (!window.confirm(`להוציא את "${r.title}" ממאגר הידע? העוזר לא ישתמש בו יותר.`)) return
    try { await api.post(`/api/knowledge/uploads/${r.id}/retire`); load() } catch (e: any) { toast(e.message, true) }
  }

  return <>
    <div className="page-head"><div><h1>מאגר ידע ל-AI</h1>
      <p>מסמכים שהעוזר ההנדסי עונה מתוכם. ידע ארצי (חוקים, תקנות, נהלים) נכלל בחיפוש של כל ועדה; מסמך של ועדה — רק בחיפוש שלה. הידע אינו מאומת ואינו כלל.</p></div></div>
    <div className="card">
      <h3>העלאת מסמכים</h3>
      <div className="user-form" style={{ padding: 0 }}>
        <label>היקף<select value={scope} onChange={e => setScope(e.target.value)}>
          <option value="national">ידע ארצי — לכל הוועדות</option>
          {dir.map(c => <option key={c.id} value={c.id}>{c.name_he} — {c.district}</option>)}</select></label>
        <label>חיפוש ועדה<input value={q} onChange={e => setQ(e.target.value)} placeholder="שם ועדה או יישוב" /></label>
        <label>סוג<select value={kind} onChange={e => setKind(e.target.value)}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        {files.length <= 1 && <label style={{ flex: 2 }}>כותרת (רשות)<input value={title} onChange={e => setTitle(e.target.value)} placeholder="לדוגמה: תקנות התכנון והבנייה (בקשה להיתר) 2016" /></label>}
        <label>קבצים (PDF, DOCX, XLSX — עד 50 MB; ZIP של מסמכים — עד 8 GB)<input id="kb-files" type="file" multiple accept=".pdf,.docx,.xlsx,.zip" onChange={e => setFiles(Array.from(e.target.files ?? []))} /></label>
        <button className="primary" disabled={busy || !files.length} onClick={upload}>{busy ? (pct !== null ? `מעלה… ${pct}%` : 'מעלה…') : `העלאה${files.length > 1 ? ` (${files.length})` : ''}`}</button>
      </div>
      {pct !== null && <progress max={100} value={pct} style={{ width: '100%', marginTop: 8 }} />}
      {log.length > 0 && <ul className="small" style={{ marginBottom: 0 }}>{log.map((x, i) => <li key={i}>{x}</li>)}</ul>}
    </div>
    {imports.length > 0 && <div className="card" style={{ marginTop: 12, padding: 0, overflowX: 'auto' }}>
      <h3 style={{ padding: '10px 12px 0' }}>ייבוא ארכיונים</h3>
      <table className="small"><thead><tr><th>ארכיון</th><th>מצב</th><th>התקדמות</th><th>נוספו</th><th>כפולים</th><th>דולגו</th><th>נכשלו</th><th>הועלה</th></tr></thead><tbody>
        {imports.map(j => <tr key={j.id}>
          <td><b>{j.filename}</b> <span className="muted">{mb(j.size)}</span>
            {j.scopes && Object.keys(j.scopes).length > 0 && <div className="muted">{Object.entries(j.scopes).map(([k, v]) => `${k}: ${v}`).join(' · ')}</div>}
            {j.server_packages > 0 && <div className="muted">{`חבילות שרת (main_system) נשמרו להתקנה: ${j.server_packages}`}</div>}
            {j.errors?.length > 0 && <details><summary className="muted">{`פירוט (${j.errors.length})`}</summary>
              <ul style={{ margin: 0 }}>{j.errors.map((e: any, i: number) => <li key={i}><span dir="auto">{e.name}</span> — {e.reason}</li>)}</ul></details>}</td>
          <td><span className={`chip ${j.status === 'done' ? 'ok' : j.status === 'failed' ? 'bad' : 'info'}`}>{IMPORT_HE[j.status] ?? j.status}</span></td>
          <td>{`${j.processed}/${j.total}`}</td><td>{j.added}</td><td>{j.duplicate}</td><td>{j.skipped}</td><td>{j.failed}</td>
          <td>{fmtDate(j.created_at)}</td></tr>)}
      </tbody></table>
    </div>}
    <div className="card" style={{ marginTop: 12, padding: 0, overflowX: 'auto' }}>
      <div className="filters-row" style={{ padding: '10px 12px 0' }}>
        <select value={filter} onChange={e => setFilter(e.target.value)}><option value="">כל המסמכים</option><option value="national">ידע ארצי</option>
          {[...new Map((rows ?? []).filter(r => r.committee_id).map(r => [r.committee_id, r.scope_he])).entries()].map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select>
        <span className="small muted">{rows ? `${rows.length} מסמכים` : ''}</span>
      </div>
      <table className="small"><thead><tr><th>מסמך</th><th>היקף</th><th>סוג</th><th>טקסט</th><th>אינדקס</th><th>הועלה</th><th></th></tr></thead><tbody>
        {(rows ?? []).map(r => <tr key={r.id} className={r.status === 'retired' ? 'muted' : ''}>
          <td><b>{r.title || '—'}</b>{r.message && <div className="muted">{r.message}</div>}</td>
          <td>{r.scope_he}</td><td>{r.kind_he}</td>
          <td>{TEXT_HE[r.text_status] ?? '—'}{r.pages ? ` · ${r.pages} עמ׳` : ''}</td>
          <td>{r.status === 'retired' ? <span className="chip">הוצא מהמאגר</span>
            : r.text_status !== 'ok' ? '—' : r.chunks && r.embedded >= r.chunks ? <span className="chip ok">מוכן לחיפוש</span>
              : <span className="chip info">בעיבוד {r.chunks ? `${r.embedded}/${r.chunks}` : ''}</span>}</td>
          <td>{fmtDate(r.uploaded_at)}</td>
          <td>{r.status !== 'retired' && <button className="sm" onClick={() => retire(r)}>הוצאה</button>}</td></tr>)}
        {rows && !rows.length && <tr><td colSpan={7} className="empty">טרם הועלו מסמכים.</td></tr>}
      </tbody></table>
    </div>
    <p className="small muted">חיפוש מילולי זמין מיד; חיפוש סמנטי זמין כשהאינדקס מוכן. מסמכים סרוקים ללא שכבת טקסט אינם נכנסים לחיפוש עד שיופעל OCR.</p>
  </>
}
