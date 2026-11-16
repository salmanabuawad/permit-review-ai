import { useEffect, useState } from 'react'
import { Citation, VERIFICATION_HE, api } from '../api'

export default function SourceDrawer({ cite, onClose }: { cite: Citation | null; onClose: () => void }) {
  const [hits, setHits] = useState<any[]>([])
  useEffect(() => {
    if (!cite) return
    const q = [cite.section, cite.title_he].filter(Boolean).join(' ')
    api.get<any>('/api/kb/search?q=' + encodeURIComponent(q))
      .then(r => setHits(r.hits.filter((h: any) => h.source_id === cite.source_id).slice(0, 4)))
      .catch(() => setHits([]))
  }, [cite])
  if (!cite) return null
  const ok = cite.verification === 'VERIFIED_READ'
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="פרטי מקור">
        <div className="card-head"><h2>אסמכתא</h2><span className="spacer" /><button onClick={onClose}>סגירה</button></div>
        <h3>{cite.title_he}</h3>
        <dl className="kv">
          <dt>מזהה מקור</dt><dd className="mono">{cite.source_id}</dd>
          <dt>סעיף</dt><dd>{cite.section ?? '—'}</dd>
          <dt>עמוד</dt><dd className="num">{cite.page ?? '—'}</dd>
          <dt>מהדורה</dt><dd>{cite.edition ?? '—'}</dd>
          <dt>מצב אימות</dt><dd><span className={'chip ' + (ok ? 'ok' : 'warn')}>{VERIFICATION_HE[cite.verification] ?? cite.verification}</span></dd>
          <dt>קישור</dt><dd>{cite.url ? <a href={cite.url} target="_blank" rel="noreferrer" className="ltr">{cite.url}</a> : '—'}</dd>
        </dl>
        {cite.quote_he && <div className="quote">"{cite.quote_he}"</div>}
        <h3 style={{ marginTop: 16 }}>קטעים בבסיס הידע</h3>
        {hits.length === 0 && <p className="muted small">לא נמצאו קטעים מתאימים לסעיף זה בבסיס הידע.</p>}
        {hits.map(h => (
          <div key={h.id} className="quote">
            <div className="small muted">{h.section}{h.page ? ` · עמ׳ ${h.page}` : ''} · {h.kind === 'quote' ? 'ציטוט' : 'תקציר (לא נוסח מקור)'}</div>
            {h.text_he}
          </div>
        ))}
        <p className="small muted">הקטעים בבסיס הידע הם תקצירים עם הפניה לעמוד. המסמך הרשמי הוא המקור המחייב.</p>
      </aside>
    </>
  )
}
