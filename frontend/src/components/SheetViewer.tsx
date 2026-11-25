import { useEffect, useState } from 'react'
import { api, openBlob } from '../api'

// Sheets of a plan that arrived as a picture rather than CAD: a DWFX converted to PDF on the AI PC, or a PDF plan.
// Shown for reading only — nothing on these sheets is measured.
interface Props { file: { id: string; filename: string; kind: string; ingest_report: any } }

export default function SheetViewer({ file }: Props) {
  const pages: number = file.ingest_report?.page_count ?? 1
  const [n, setN] = useState(1)
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { setN(1) }, [file.id])
  useEffect(() => {
    let live = true, made: string | null = null
    setUrl(null); setErr(null)
    api.blob(`/api/files/${file.id}/page/${n}.png`)
      .then(b => { if (live) { made = URL.createObjectURL(b); setUrl(made) } })
      .catch(e => live && setErr(String(e?.message ?? e)))
    return () => { live = false; if (made) URL.revokeObjectURL(made) }
  }, [file.id, n])

  return (
    <div className="viewer">
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
        <span className="small"><span className="ltr">{file.filename}</span>{file.kind === 'dwfx' && ' · הומר מ-DWFX'}</span>
        <span className="spacer" />
        {Array.from({ length: pages }, (_, i) => i + 1).map(i => (
          <button key={i} className={'sm' + (i === n ? ' active' : '')} onClick={() => setN(i)}>גיליון {i}</button>))}
        {url && <button className="sm" onClick={() => openBlob(`/api/files/${file.id}/page/${n}.png`)}>פתיחה בגודל מלא</button>}
      </div>
      {err ? <div className="empty">{err}</div>
        : url ? <img src={url} alt={`גיליון ${n} — ${file.filename}`} style={{ width: '100%', height: 'auto', background: '#fff' }} />
          : <div className="empty">טוען גיליון…</div>}
      <div className="small muted" style={{ marginTop: 4 }}>תמונה של השרטוט לקריאה בלבד — לא נמדדה. מדידות דורשות DXF/DWG.</div>
    </div>
  )
}
