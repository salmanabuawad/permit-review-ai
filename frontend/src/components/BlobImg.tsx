import { useEffect, useState } from 'react'
import { api } from '../api'

/** An image from the API, fetched with the session and the selected authority (a plain <img src> sends neither header). */
export default function BlobImg({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [url, setUrl] = useState('')
  const [err, setErr] = useState(false)
  useEffect(() => {
    let cancel = false, made = ''
    setUrl(''); setErr(false)
    api.blob(src).then(b => { if (!cancel) { made = URL.createObjectURL(b); setUrl(made) } }).catch(() => { if (!cancel) setErr(true) })
    return () => { cancel = true; if (made) URL.revokeObjectURL(made) }
  }, [src])
  if (err) return <div className="small muted">לא ניתן להציג את העמוד</div>
  return url ? <img src={url} alt={alt} className={className} /> : <div className="small muted">טוען…</div>
}
