import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'

const VENDORS = ['BarTech', 'Complot', 'other', 'unknown']
const VENDOR_HE: Record<string, string> = { BarTech: 'BarTech', Complot: 'Complot', other: 'אחר', unknown: 'לא ידוע' }
const KIND_HE: Record<string, string> = { local: 'מקומית', regional: 'מרחבית' }

/** National register of the local planning committees: identity, sites, systems, sources and knowledge status. */
export default function Committees() {
  const { toast } = useApp()
  const [d, setD] = useState<any>(null)
  const [q, setQ] = useState(''), [district, setDistrict] = useState(''), [vendor, setVendor] = useState(''), [status, setStatus] = useState('')
  const [open, setOpen] = useState<string | null>(null), [edit, setEdit] = useState<any>({}), [busy, setBusy] = useState(false)
  const load = () => api.get<any>('/api/committees').then(setD).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [])
  const rows = useMemo(() => (d?.committees ?? []).filter((c: any) =>
    (!district || c.district === district) && (!vendor || c.vendor === vendor) && (!status || c.kb_status === status) &&
    (!q || c.name_he.includes(q) || c.settlements.some((t: string) => t.includes(q)))), [d, q, district, vendor, status])
  const save = async (id: string) => {
    setBusy(true)
    try { await api.patch(`/api/committees/${id}`, edit); toast('נשמר'); setOpen(null); await load() }
    catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  if (!d) return <div className="empty">טוען…</div>
  const t = d.totals
  const host = (u: string | null) => { try { return u ? new URL(u).hostname.replace(/^www\./, '') : '' } catch { return u ?? '' } }
  return <>
    <div className="page-head"><div><h1>מאגר ועדות ארצי</h1>
      <p>כל הוועדות המקומיות והמרחביות לפי <a href={d.committees[0]?.registry_source?.url} target="_blank" rel="noreferrer">רשימת מינהל התכנון</a> (עודכנה {d.committees[0]?.registry_source?.page_updated}, נקראה {d.committees[0]?.registry_source?.retrieved}). בסיס הידע נבנה מראש לכל ועדה, גם לפני שרשות מצטרפת.</p></div></div>
    <div className="summary-strip">
      <div><b className="num">{t.committees}</b><span>ועדות ({t.regional} מרחביות)</span></div>
      {Object.entries(t.by_vendor).map(([k, n]) => <div key={k}><b className="num">{n as number}</b><span>{VENDOR_HE[k] ?? k}</span></div>)}
      {Object.entries(t.by_status).map(([k, n]) => <div key={k}><b className="num">{n as number}</b><span>{d.status_he[k] ?? k}</span></div>)}
    </div>
    <div className="filters-row">
      <input placeholder="ועדה או יישוב" value={q} onChange={e => setQ(e.target.value)} />
      <select value={district} onChange={e => setDistrict(e.target.value)}><option value="">כל המחוזות</option>{Object.keys(t.by_district).map(k => <option key={k} value={k}>{k} ({t.by_district[k]})</option>)}</select>
      <select value={vendor} onChange={e => setVendor(e.target.value)}><option value="">כל הספקים</option>{VENDORS.map(k => <option key={k} value={k}>{VENDOR_HE[k]}</option>)}</select>
      <select value={status} onChange={e => setStatus(e.target.value)}><option value="">כל מצבי הידע</option>{Object.keys(d.status_he).map(k => <option key={k} value={k}>{d.status_he[k]}</option>)}</select>
      <span className="small muted">{rows.length} מוצגות</span>
    </div>
    <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
      <table><thead><tr><th>ועדה</th><th>מחוז</th><th>יישובים</th><th>אתר הוועדה</th><th>איתור בקשות</th><th>ספק</th><th>בסיס ידע</th></tr></thead><tbody>
        {rows.map((c: any) => <Fragment key={c.id}>
          <tr className={d.can_edit ? 'clickable' : ''} onClick={() => { if (!d.can_edit) return; setOpen(open === c.id ? null : c.id); setEdit({ committee_code: c.committee_code ?? '', engineering_url: c.engineering_url ?? '', request_search_url: c.request_search_url ?? '', vendor: c.vendor }) }}>
            <td><b>{c.name_he}</b>{c.kind === 'regional' && <span className="chip outline" style={{ marginInlineStart: 6 }}>{KIND_HE[c.kind]}</span>}{c.committee_code && <div className="small muted ltr">{c.committee_code}</div>}</td>
            <td>{c.district}</td>
            <td className="small" title={c.settlements.join(' · ')}>{c.settlements.length === 1 && c.settlements[0] === c.name_he ? '—' : c.settlements.join(' · ')}</td>
            <td className="small ltr">{c.website_url ? <a href={c.website_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>{host(c.website_url)}</a> : '—'}</td>
            <td className="small ltr">{c.request_search_url ? <a href={c.request_search_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>{host(c.request_search_url)}</a> : <span className="muted">טרם אותר</span>}</td>
            <td title={c.vendor_evidence ?? ''}>{VENDOR_HE[c.vendor] ?? c.vendor}</td>
            <td><span className={'chip ' + (c.kb_status === 'IN_SYSTEM' ? 'ok' : c.kb_status === 'SOURCES_FOUND' ? 'warn' : c.kb_status === 'BLOCKED' ? 'bad' : 'outline')}>{c.kb_status_he}</span>
              {c.authorities.length > 0 && <div className="small muted">{c.authorities.map((a: any) => a.name_he).join(', ')}</div>}
              {c.sources.length > 0 && <div className="small muted">{c.sources.length} מקורות</div>}</td>
          </tr>
          {open === c.id && <tr><td colSpan={7}><form className="user-form" onSubmit={e => { e.preventDefault(); save(c.id) }}>
            <label>קוד ועדה רשמי<input dir="ltr" value={edit.committee_code} onChange={e => setEdit({ ...edit, committee_code: e.target.value })} /></label>
            <label>אתר הנדסה ורישוי<input dir="ltr" value={edit.engineering_url} onChange={e => setEdit({ ...edit, engineering_url: e.target.value })} placeholder="https://" /></label>
            <label>מערכת איתור בקשות<input dir="ltr" value={edit.request_search_url} onChange={e => setEdit({ ...edit, request_search_url: e.target.value })} placeholder="https://" /></label>
            <label>ספק<select value={edit.vendor} onChange={e => setEdit({ ...edit, vendor: e.target.value })}>{VENDORS.map(k => <option key={k} value={k}>{VENDOR_HE[k]}</option>)}</select></label>
            <button className="primary" disabled={busy}>שמירה</button><button type="button" onClick={() => setOpen(null)}>ביטול</button>
            {c.vendor_evidence && <span className="small muted">ספק: {c.vendor_evidence}</span>}
          </form></td></tr>}
        </Fragment>)}
        {!rows.length && <tr><td colSpan={7} className="empty">אין ועדות התואמות לסינון</td></tr>}
      </tbody></table>
    </div>
  </>
}
