import { useEffect, useState } from 'react'
import { VERIFICATION_HE, api } from '../api'

const CAT_HE: Record<string, string> = { TENDER: 'מכרז', LAW: 'חוק', REGULATION: 'תקנות', STATUTORY_PLAN: 'תכנית סטטוטורית', LOCAL_POLICY: 'מדיניות/הנחיות מקומיות', GOV_GUIDANCE: 'הנחיות מינהל התכנון', INTERNAL: 'פנימי', DEMO: 'הדגמה' }

export default function Sources() {
  const [sources, setSources] = useState<any[]>([])
  const [q, setQ] = useState('')
  const [res, setRes] = useState<any>(null)
  useEffect(() => { api.get<any[]>('/api/sources').then(setSources) }, [])
  const search = async () => { if (q.trim()) setRes(await api.get('/api/kb/search?q=' + encodeURIComponent(q))) }
  return (
    <>
      <div className="page-head"><div><h1>מקורות ובסיס ידע</h1><p>רשם מקורות עם מצב אימות, וחיפוש באסמכתאות. כל תשובה מוצגת עם מקור, סעיף ועמוד.</p></div></div>
      <div className="card">
        <div className="card-head"><h3>חיפוש בבסיס הידע</h3></div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input style={{ flex: 1 }} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()} placeholder="למשל: נסיגת חדר גג, תמונות בניין קיים, הסכמת בעלים" />
          <button className="primary" onClick={search}>חיפוש</button>
        </div>
        {res && (
          <div style={{ marginTop: 12 }}>
            <p className="small muted">{res.note_he} · ספק: <span className="mono">{res.provider}</span></p>
            {res.hits.length === 0 && <div className="empty">לא נמצאו קטעים. המערכת אינה ממציאה תשובה ללא מקור.</div>}
            {res.hits.map((h: any) => (
              <div key={h.id} className="quote">
                <div className="small"><b>{h.source_title_he}</b> · {h.section}{h.page ? ` · עמ׳ ${h.page}` : ''} · <span className="chip outline">{h.kind === 'quote' ? 'ציטוט' : 'תקציר'}</span></div>
                <div>{h.text_he}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card">
        <h3>רשם מקורות</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>מקור</th><th>קטגוריה</th><th>מהדורה / תאריך</th><th>אימות</th><th>הערות</th></tr></thead>
          <tbody>{sources.map(s => (
            <tr key={s.id}>
              <td><b>{s.title_he}</b><div className="mono small muted">{s.id}</div>{s.url && <a className="small ltr" href={s.url} target="_blank" rel="noreferrer">{s.url}</a>}</td>
              <td className="small">{CAT_HE[s.category] ?? s.category}</td>
              <td className="small">{s.edition ?? '—'}</td>
              <td><span className={'chip ' + (s.verification === 'VERIFIED_READ' ? 'ok' : s.verification === 'DEMO' ? 'demo' : 'warn')}>{VERIFICATION_HE[s.verification] ?? s.verification}</span></td>
              <td className="small" dir="ltr" style={{ textAlign: 'left' }}>{s.notes ?? ''}</td>
            </tr>))}</tbody>
        </table></div>
      </div>
    </>
  )
}
