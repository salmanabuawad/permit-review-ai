import { useState } from 'react'
import { api, ApiError, setAuthority } from '../api'

/** Sign-in screen: one administrator; the server sets an HttpOnly session cookie. */
export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      await api.post('/api/auth/login', { username, password })
      setAuthority('')
      window.location.assign('/')
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : 'שגיאת רשת')
      setBusy(false)
    }
  }

  return (
    <div className="login-center">
      <form className="login" onSubmit={submit}>
        <h1>בדיקת היתרי בנייה</h1>
        <div className="hint">כניסה לצוותי הרשויות והוועדות לתכנון ובנייה</div>
        <label className="f">שם משתמש
          <input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required autoFocus dir="ltr" />
        </label>
        <label className="f">סיסמה
          <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required dir="ltr" />
        </label>
        {err && <div className="login-err" role="alert">{err}</div>}
        <button className="primary" type="submit" disabled={busy}>{busy ? 'מתחבר…' : 'כניסה'}</button>
      </form>
    </div>
  )
}
