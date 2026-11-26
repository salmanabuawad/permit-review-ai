import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { OP_HE, api, openBlob } from '../api'
import { useApp } from '../App'

const FETCH_HE: Record<string, [string, string]> = {
  ok: ['נשלף', 'ok'], not_modified: ['ללא שינוי (שרת)', 'ok'], manual: ['הועלה ידנית', 'outline'],
  blocked: ['חסום לשליפה אוטומטית', 'bad'], unreachable: ['האתר לא זמין', 'bad'], error: ['שגיאה', 'bad'],
  too_large: ['גדול מדי', 'warn'],
}
const CHANGE_HE: Record<string, [string, string]> = { new: ['חדש', 'warn'], changed: ['השתנה', 'warn'], unchanged: ['ללא שינוי', 'outline'] }
const KIND_HE: Record<string, string> = { page: 'עמוד אינדקס', document: 'מסמך', manual: 'הועלה ידנית' }
const DRAFT_KIND_HE: Record<string, string> = { numeric_limit: 'מגבלה מספרית', required_document: 'מסמך נדרש', prohibition: 'איסור' }
const DRAFT_STATUS_HE: Record<string, string> = { open: 'ממתין', for_authoring: 'לכתיבת כלל', dismissed: 'נדחה', superseded: 'לא קיים בגרסה החדשה' }

const fmtDT = (iso?: string | null) => iso ? new Date(iso).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' }) : '—'
const fmtSize = (n?: number | null) => n == null ? '' : n > 2 ** 20 ? `${(n / 2 ** 20).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`

export default function SourceMonitor() {
  const { can, toast } = useApp()
  const [data, setData] = useState<any>(null)
  const [openDoc, setOpenDoc] = useState<any>(null)
  const [regSources, setRegSources] = useState<any[]>([])
  const poll = useRef<number | null>(null)
  const canCrawl = can('source.crawl')
  const canSchedule = can('source.schedule')

  const load = () => api.get<any>('/api/source-monitor').then(d => {
    setData(d)
    if (['running', 'queued'].includes(d.last_crawl?.status)) schedule()
    return d
  }).catch(e => toast(e.message, true))
  const schedule = () => { if (poll.current) window.clearTimeout(poll.current); poll.current = window.setTimeout(load, 2500) }
  useEffect(() => {
    load()
    api.get<any[]>('/api/sources').then(setRegSources)
    return () => { if (poll.current) window.clearTimeout(poll.current) }
  }, [])

  const crawl = async () => {
    try { await api.post('/api/source-monitor/crawl'); toast('הסריקה נשלחה לסורק'); load() }
    catch (e: any) { toast(e.message, true) }
  }
  const setSchedule = async (schedule: string) => {
    try { await api.put('/api/source-monitor/schedule', { schedule }); toast('תזמון הסריקות עודכן'); load() }
    catch (e: any) { toast(e.message, true) }
  }
  const ack = async (id: number) => {
    try { await api.post(`/api/source-monitor/documents/${id}/acknowledge`); load() } catch (e: any) { toast(e.message, true) }
  }
  const upload = async (file: File, target: { document_id?: number; source_id?: string }) => {
    const fd = new FormData()
    fd.append('file', file)
    if (target.document_id) fd.append('document_id', String(target.document_id))
    if (target.source_id) fd.append('source_id', target.source_id)
    try { await api.upload('/api/source-monitor/upload', fd); toast('המסמך נקלט'); load() } catch (e: any) { toast(e.message, true) }
  }

  const lc = data?.last_crawl
  const sm = lc?.summary ?? {}
  const running = lc?.status === 'running' || lc?.status === 'queued'
  const docs: any[] = data?.documents ?? []
  return (
    <>
      <div className="page-head">
        <div><h1>סריקת מקורות לכללים</h1><p>שליפת המסמכים הרשמיים מרשם המקורות, זיהוי מסמכים חדשים ושינויים, והצעת סעיפים לכתיבת כללים.</p></div>
        <span className="spacer" />
        <button onClick={() => openBlob('/api/source-monitor/drafts.yaml', 'rule_drafts.yaml').catch(e => toast(e.message, true))}
          disabled={!data?.drafts?.for_authoring} title="שלדי כללים מהטיוטות שסומנו לכתיבת כלל">ייצוא טיוטות ({data?.drafts?.for_authoring ?? 0})</button>
        {data && (canSchedule
          ? <label className="row small">תזמון סריקות
              <select value={data.schedule} onChange={e => setSchedule(e.target.value)} aria-label="תזמון סריקות">
                {Object.entries(data.schedules ?? {}).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}
              </select></label>
          : <span className="small muted">תזמון סריקות: {data.schedules?.[data.schedule] ?? data.schedule}</span>)}
        {canCrawl && <button className="primary" onClick={crawl} disabled={running}>{running ? 'סורק…' : 'סריקה עכשיו'}</button>}
      </div>
      <div className="notice info small" style={{ marginBottom: 14 }}>
        מסמך שנשלף <b>אינו משנה אף כלל</b>. המערכת שומרת כל גרסה (SHA-256), מסמנת מסמכים חדשים ושינויים, ומציעה סעיפים שנראים כמו דרישה (מספר + יחידה, מסמך נדרש, איסור).
        כותב כללים מסמן הצעה "לכתיבת כלל", משלים תחולה ובדיקה, והכלל נכנס לתוקף רק לאחר אישור מהנדס העיר / מנהל אגף ב<Link to="/rules">מאגר הכללים</Link>.
        נשלפים רק אתרים שברשם: <span className="ltr small">{(data?.hosts ?? []).join(' · ')}</span>
      </div>

      <div className="summary-strip">
        <div><b className="small">{lc?.status === 'queued' ? 'ממתינה לסורק…' : running ? 'רצה כעת…' : lc ? fmtDT(lc.finished_at ?? lc.started_at) : 'טרם בוצעה'}</b><span>סריקה אחרונה{lc?.status === 'failed' ? ' — נכשלה' : ''}</span></div>
        <div><b className="num">{sm.checked ?? 0}</b><span>כתובות נבדקו</span></div>
        <div className={sm.new ? 's-ok' : ''}><b className="num">{sm.new ?? 0}</b><span>חדשים</span></div>
        <div className={sm.changed ? 's-ok' : ''}><b className="num">{sm.changed ?? 0}</b><span>השתנו</span></div>
        <div><b className="num">{(sm.blocked ?? 0) + (sm.unreachable ?? 0) + (sm.error ?? 0)}</b><span>לא נשלפו</span></div>
        <div><b className="num">{data?.drafts?.open ?? 0}</b><span>הצעות ממתינות</span></div>
      </div>
      {lc?.summary?.error && <div className="notice small" style={{ marginBottom: 14 }}>שגיאה בסריקה: {lc.summary.error}</div>}

      <div className="card">
        <div className="card-head"><h3>מסמכים ועמודים</h3>{data?.attention > 0 && <span className="chip warn">{data.attention} ממתינים לעיון</span>}</div>
        <div className="table-wrap"><table>
          <thead><tr><th>מקור</th><th>שליפה</th><th>שינוי</th><th>היקף</th><th>הצעות</th><th></th></tr></thead>
          <tbody>
            {docs.map(d => {
              const fs = FETCH_HE[d.fetch_status] ?? [d.fetch_status ?? '—', 'outline']
              const cs = d.change_state ? CHANGE_HE[d.change_state] : null
              const failed = ['blocked', 'unreachable', 'error'].includes(d.fetch_status)
              const isUrl = d.url.startsWith('http')
              return (
                <tr key={d.id}>
                  <td style={{ maxWidth: 420 }}>
                    <b>{d.title ?? '—'}</b>
                    <div className="small muted">{KIND_HE[d.kind] ?? d.kind}{d.source_id ? <> · <span className="mono">{d.source_id}</span></> : d.kind !== 'page' ? <> · <span className="chip warn">לא ברשם המקורות</span></> : null}</div>
                    {isUrl && <a className="small ltr" style={{ wordBreak: 'break-all' }} href={d.url} target="_blank" rel="noreferrer">{d.url}</a>}
                    {d.message && <div className="small muted">{d.message}</div>}
                  </td>
                  <td><span className={'chip ' + fs[1]}>{fs[0]}</span><div className="small muted">{fmtDT(d.last_checked)}</div></td>
                  <td>{cs ? <span className={'chip ' + (d.acknowledged ? 'outline' : cs[1])}>{cs[0]}{d.acknowledged && d.change_state !== 'unchanged' ? ' · נבדק' : ''}</span> : '—'}
                    {canCrawl && cs && !d.acknowledged && d.change_state !== 'unchanged' && <div><button className="link-btn small" onClick={() => ack(d.id)}>סימון כנבדק</button></div>}</td>
                  <td className="small">{d.kind === 'page' ? `${d.links} מסמכים מקושרים` : [d.page_count ? `${d.page_count} עמ׳` : '', fmtSize(d.size)].filter(Boolean).join(' · ') || '—'}</td>
                  <td className="small">{d.drafts.open ? <b>{d.drafts.open} ממתינות</b> : null}{d.drafts.for_authoring ? <div>{d.drafts.for_authoring} לכתיבת כלל</div> : null}{!d.drafts.open && !d.drafts.for_authoring ? '—' : null}</td>
                  <td className="nowrap">
                    {d.has_file && <button className="sm" onClick={() => openBlob(`/api/source-monitor/documents/${d.id}/file`).catch(e => toast(e.message, true))}>פתיחה</button>}{' '}
                    {d.page_count > 0 && <button className="sm" onClick={() => setOpenDoc(d)}>הצעות</button>}{' '}
                    {canCrawl && d.kind !== 'page' && (failed || d.kind === 'manual') && <UploadButton label="העלאה ידנית" onFile={f => upload(f, { document_id: d.id })} />}
                  </td>
                </tr>
              )
            })}
            {!docs.length && <tr><td colSpan={6} className="empty">{running ? 'הסריקה הראשונה רצה…' : 'טרם בוצעה סריקה. לחצו "סריקה עכשיו".'}</td></tr>}
          </tbody>
        </table></div>
      </div>

      {canCrawl && <ManualSource sources={regSources} onUpload={(f, sid) => upload(f, { source_id: sid })} />}
      {openDoc && <DraftsDrawer doc={openDoc} canDecide={canCrawl} onClose={() => { setOpenDoc(null); load() }} />}
    </>
  )
}

function UploadButton({ label, onFile }: { label: string; onFile: (f: File) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <button className="sm" onClick={() => ref.current?.click()}>{label}</button>
      <input ref={ref} type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" hidden onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
    </>
  )
}

function ManualSource({ sources, onUpload }: { sources: any[]; onUpload: (f: File, sid: string) => void }) {
  const [sid, setSid] = useState('')
  return (
    <div className="card">
      <h3>העלאת מסמך למקור ברשם</h3>
      <p className="small muted">לאתרים שחוסמים שליפה אוטומטית (למשל gov.il) או למקור ללא כתובת: שמרו את המסמך הרשמי והעלו אותו כאן. הוא יעובד כמו מסמך שנשלף, ויסומן "הועלה ידנית".</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={sid} onChange={e => setSid(e.target.value)} aria-label="מקור ברשם" style={{ minWidth: 0, maxWidth: '100%', flex: '1 1 260px' }}>
          <option value="">בחירת מקור…</option>
          {sources.filter(s => s.category !== 'DEMO').map(s => <option key={s.id} value={s.id}>{s.title_he}</option>)}
        </select>
        {sid ? <UploadButton label="בחירת קובץ" onFile={f => onUpload(f, sid)} /> : <button className="sm" disabled>בחירת קובץ</button>}
      </div>
    </div>
  )
}

function DraftsDrawer({ doc, canDecide, onClose }: { doc: any; canDecide: boolean; onClose: () => void }) {
  const { toast } = useApp()
  const [drafts, setDrafts] = useState<any[]>([])
  const [kind, setKind] = useState('all')
  const [status, setStatus] = useState('open')
  const [page, setPage] = useState<number | null>(null)
  const [pageUrl,setPageUrl]=useState('')
  useEffect(()=>{let cancel=false;let url='';setPageUrl('');if(page) api.blob(`/api/source-monitor/documents/${doc.id}/page/${page}.png`).then(b=>{if(!cancel){url=URL.createObjectURL(b);setPageUrl(url)}}).catch(e=>toast(e.message,true));return ()=>{cancel=true;if(url)URL.revokeObjectURL(url)}},[doc.id,page])
  const load = () => api.get<any[]>(`/api/source-monitor/documents/${doc.id}/drafts`).then(setDrafts).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [doc.id])
  const decide = async (id: number, st: string) => {
    const note = st === 'dismissed' ? window.prompt('סיבת הדחייה (לא חובה):') ?? undefined : undefined
    try { await api.post(`/api/source-monitor/drafts/${id}`, { status: st, note }); load() } catch (e: any) { toast(e.message, true) }
  }
  const shown = drafts.filter(d => (kind === 'all' || d.kind === kind) && (status === 'all' || d.status === status))
  const cnt = (st: string) => drafts.filter(d => st === 'all' || d.status === st).length
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer drawer-wide" role="dialog" aria-label="הצעות לכללים">
        <div className="card-head"><h3>הצעות לכללים — {doc.title}</h3><span className="spacer" /><button onClick={onClose}>סגירה</button></div>
        <p className="small muted">סעיפים שזוהו אוטומטית לפי נוסח (מספר + יחידה, מסמך נדרש, איסור). מספר הסעיף משוער — סדר הטקסט ב־PDF משתבש בכיווניות. יש לוודא מול העמוד.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <div className="seg">{[['open', 'ממתינות'], ['for_authoring', 'לכתיבת כלל'], ['dismissed', 'נדחו'], ['all', 'הכול']].map(([k, l]) =>
            <button key={k} className={status === k ? 'active' : ''} onClick={() => setStatus(k)}>{l} ({cnt(k)})</button>)}</div>
          <div className="seg">{[['all', 'כל הסוגים'], ...Object.entries(DRAFT_KIND_HE)].map(([k, l]) =>
            <button key={k} className={kind === k ? 'active' : ''} onClick={() => setKind(k)}>{l}</button>)}</div>
        </div>
        {page && (
          <div style={{ marginBottom: 10 }}>
            <div className="card-head"><b>עמוד {page}</b><span className="spacer" /><button className="sm" onClick={() => setPage(null)}>הסתרת העמוד</button></div>
            {pageUrl && <img className="page-img" alt={`עמוד ${page} במסמך המקור`} src={pageUrl} />}
          </div>
        )}
        {shown.map(d => (
          <div key={d.id} className="app-card">
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="chip outline">{DRAFT_KIND_HE[d.kind] ?? d.kind}</span>
              <button className="link-btn small" onClick={() => setPage(d.page)}>עמ׳ {d.page}</button>
              {d.section && <span className="small muted">סעיף ~{d.section}</span>}
              {d.topics.map((t: string) => <span key={t} className="chip">{t}</span>)}
              <span className="spacer" />
              {d.status !== 'open' && <span className={'chip ' + (d.status === 'for_authoring' ? 'ok' : 'outline')}>{DRAFT_STATUS_HE[d.status] ?? d.status}</span>}
            </div>
            <div className="quote" style={{ marginTop: 6 }}>{d.text_he}</div>
            {d.values.length > 0 && <div className="small">ערכים: {d.values.map((v: any, i: number) =>
              <span key={i} className="chip outline ltr" style={{ marginInlineEnd: 4 }}>{v.op ? OP_HE[v.op] ?? v.op : '?'} {v.value} {v.unit}</span>)}</div>}
            {d.note && <div className="small muted">הערה: {d.note}</div>}
            {canDecide && d.status !== 'superseded' && (
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                {d.status !== 'for_authoring' && <button className="sm primary" onClick={() => decide(d.id, 'for_authoring')}>לכתיבת כלל</button>}
                {d.status !== 'dismissed' && <button className="sm" onClick={() => decide(d.id, 'dismissed')}>דחייה</button>}
                {d.status !== 'open' && <button className="sm" onClick={() => decide(d.id, 'open')}>החזרה להמתנה</button>}
              </div>
            )}
          </div>
        ))}
        {!shown.length && <div className="empty">אין הצעות בסינון הזה</div>}
      </aside>
    </>
  )
}
