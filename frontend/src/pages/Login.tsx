import { useEffect, useState } from 'react'
import { api, ApiError, setAuthority } from '../api'
import LangPicker from '../components/LangPicker'

const SIGNUP_RESULT: Record<string, { ok: boolean; text: string }> = {
  pending: { ok: true, text: 'כתובת הדוא״ל אומתה. בקשת ההרשמה ממתינה לאישור מנהל המערכת — תישלח הודעה כשהחשבון יאושר.' },
  approved: { ok: true, text: 'כתובת הדוא״ל אומתה והחשבון פעיל. אפשר להיכנס.' },
  invalid: { ok: false, text: 'קישור האימות אינו תקף או שפג תוקפו. אפשר להירשם מחדש.' },
}

/** Where to go after signing in: the application page the user was sent from (same-origin paths only). */
export function nextPath(): string {
  const n = new URLSearchParams(window.location.search).get('next') ?? ''
  return n.startsWith('/') && !n.startsWith('//') && !n.startsWith('/\\') && !n.startsWith('/login') ? n : '/'
}

/** Sign-in screen (the server sets an HttpOnly session cookie), and self sign-up for engineers and architects. */
export default function Login() {
  const [view, setView] = useState<'login' | 'signup' | 'sent'>(new URLSearchParams(window.location.search).has('register') ? 'signup' : 'login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [signup, setSignup] = useState<{ mode: string; professions: Record<string, string> } | null>(null)
  const result = SIGNUP_RESULT[new URLSearchParams(window.location.search).get('signup') ?? '']

  useEffect(() => { api.get<any>('/api/auth/signup').then(setSignup).catch(() => setSignup(null)) }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      await api.post('/api/auth/login', { username, password })
      setAuthority('')
      window.location.assign(nextPath())
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : 'שגיאת רשת')
      setBusy(false)
    }
  }

  if (view === 'signup' && signup) return <Signup professions={signup.professions} onSent={() => setView('sent')} onBack={() => setView('login')} />

  return (
    <div className="login-center">
      <form className="login" onSubmit={submit}>
        <div className="login-top"><b>Permit360</b><LangPicker /></div>
        <h1>בדיקת היתרי בנייה</h1>
        <div className="hint">כניסה לצוותי הרשויות והוועדות לתכנון ובנייה, ולמהנדסים, אדריכלים ובעלי נכסים ב-Permit360 Pro</div>
        {view === 'sent' && <div className="login-ok" role="status">נשלח קישור אימות לכתובת הדוא״ל. יש לפתוח אותו בתוך 48 שעות.</div>}
        {view === 'login' && result && <div className={result.ok ? 'login-ok' : 'login-err'} role="status">{result.text}</div>}
        <label className="f">שם משתמש
          <input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required autoFocus dir="ltr" />
        </label>
        <label className="f">סיסמה
          <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required dir="ltr" />
        </label>
        {err && <div className="login-err" role="alert">{err}</div>}
        <button className="primary" type="submit" disabled={busy}>{busy ? 'מתחבר…' : 'כניסה'}</button>
        {signup && signup.mode !== 'off' && <div className="login-alt">
          מהנדס/ת, אדריכל/ית או בעל/ת נכס? <button type="button" className="link" onClick={() => { setErr(null); setView('signup') }}>הרשמה ל-Permit360 Pro</button>
        </div>}
        <div className="login-alt"><a href="/">← דף הבית</a></div>
      </form>
    </div>
  )
}

function Signup({ professions, onSent, onBack }: { professions: Record<string, string>; onSent: () => void; onBack: () => void }) {
  const [f, setF] = useState({ display_name: '', email: '', username: '', password: '', password2: '', profession: '', license_number: '', organization: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    if (f.password !== f.password2) { setErr('הסיסמאות אינן זהות'); return }
    setBusy(true)
    try {
      const { password2, ...body } = f
      if (body.profession === 'owner') body.license_number = ''
      await api.post('/api/auth/signup', body)
      onSent()
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : 'שגיאת רשת')
      setBusy(false)
    }
  }

  return (
    <div className="login-center">
      <form className="login" onSubmit={submit}>
        <div className="login-top"><b>Permit360</b><LangPicker /></div>
        <h1>הרשמה ל-Permit360 Pro</h1>
        <div className="hint">למהנדסים, אדריכלים והנדסאים המכינים בקשות להיתר, ולבעלי נכסים ומבקשי היתר. לאחר אימות הדוא״ל הבקשה נבדקת ומאושרת.</div>
        <label className="f">שם מלא<input required maxLength={200} value={f.display_name} onChange={set('display_name')} autoComplete="name" autoFocus /></label>
        <label className="f">דוא״ל<input type="email" required dir="ltr" value={f.email} onChange={set('email')} autoComplete="email" /></label>
        <label className="f">סוג חשבון
          <select required value={f.profession} onChange={set('profession')}>
            <option value="" disabled>בחירה…</option>
            {Object.entries(professions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {f.profession !== 'owner' && <label className="f">מספר רישיון / רישום (לא חובה)<input dir="ltr" maxLength={40} value={f.license_number} onChange={set('license_number')} /></label>}
        <label className="f">משרד / ארגון (לא חובה)<input maxLength={200} value={f.organization} onChange={set('organization')} autoComplete="organization" /></label>
        <label className="f">שם משתמש<input required dir="ltr" value={f.username} onChange={set('username')} placeholder="first.last" autoComplete="username" /></label>
        <label className="f">סיסמה (לפחות 10 תווים)<input type="password" required minLength={10} dir="ltr" value={f.password} onChange={set('password')} autoComplete="new-password" /></label>
        <label className="f">אימות סיסמה<input type="password" required minLength={10} dir="ltr" value={f.password2} onChange={set('password2')} autoComplete="new-password" /></label>
        {err && <div className="login-err" role="alert">{err}</div>}
        <button className="primary" type="submit" disabled={busy}>{busy ? 'שולח…' : 'הרשמה'}</button>
        <div className="login-alt"><button type="button" className="link" onClick={onBack}>חזרה לכניסה</button></div>
      </form>
    </div>
  )
}
