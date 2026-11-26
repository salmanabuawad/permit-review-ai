import { useState } from 'react'
import { api, ApiError } from '../api'

/** Replace your own password. `forced`: shown instead of the app until a password set by an administrator is replaced. */
export default function ChangePassword({ forced, onDone, onCancel }: { forced?: boolean; onDone: () => void; onCancel?: () => void }) {
  const [current, setCurrent] = useState(''), [next, setNext] = useState(''), [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null)
    if (next !== again) { setErr('הסיסמאות החדשות אינן זהות'); return }
    setBusy(true)
    try { await api.post('/api/auth/password', { current, new: next }); onDone() }
    catch (x) { setErr(x instanceof ApiError ? x.message : 'שגיאת רשת'); setBusy(false) }
  }
  const form = <form className="login" onSubmit={submit}>
    <h1>החלפת סיסמה</h1>
    <div className="hint">{forced ? 'הסיסמה נקבעה על ידי מנהל המערכת — יש לבחור סיסמה חדשה לפני הכניסה.' : 'לפחות 10 תווים, ללא שם המשתמש. חיבורים אחרים שלך ינותקו.'}</div>
    <label className="f">סיסמה נוכחית<input type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} required autoFocus dir="ltr" /></label>
    <label className="f">סיסמה חדשה<input type="password" autoComplete="new-password" minLength={10} value={next} onChange={e => setNext(e.target.value)} required dir="ltr" /></label>
    <label className="f">סיסמה חדשה שוב<input type="password" autoComplete="new-password" minLength={10} value={again} onChange={e => setAgain(e.target.value)} required dir="ltr" /></label>
    {err && <div className="login-err" role="alert">{err}</div>}
    <button className="primary" type="submit" disabled={busy}>{busy ? 'שומר…' : 'שמירה'}</button>
    {onCancel && <button type="button" onClick={onCancel}>ביטול</button>}
  </form>
  return forced ? <div className="login-center">{form}</div>
    : <div className="modal-back" role="dialog" aria-modal="true" onClick={e => { if (e.target === e.currentTarget) onCancel?.() }}>{form}</div>
}
