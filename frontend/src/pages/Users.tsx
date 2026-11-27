import { useEffect, useState } from 'react'
import { api, fmtDate } from '../api'
import { useApp } from '../App'

interface Row { id: string; display_name: string; role: string; role_he: string; kind: 'home' | 'member'; home_authority: string | null
  username: string | null; login: 'db' | 'legacy' | 'none'; active: boolean; must_change: boolean; last_login_at: string | null; signup_state?: string | null }

/** Role choices grouped by user level (committee admin / committee user / end user). */
function roleOptions(roles: { id: string; label_he: string; tier?: string; tier_he?: string }[]) {
  const groups: Record<string, typeof roles> = {}
  roles.forEach(r => { (groups[r.tier_he ?? ''] ??= []).push(r) })
  return Object.entries(groups).map(([g, rs]) => g ? <optgroup key={g} label={g}>{rs.map(r => <option key={r.id} value={r.id}>{r.label_he}</option>)}</optgroup>
    : rs.map(r => <option key={r.id} value={r.id}>{r.label_he}</option>))
}

/** The authority's users: logins, roles, membership of people from other authorities, password resets. */
const PENDING = ['EMAIL_PENDING', 'APPROVAL_PENDING']
interface SignupRow { username: string; display_name: string | null; email: string | null; state: string; profession_he: string | null
  license_number: string | null; organization: string | null; requested_at: string | null; verified_at: string | null }

/** Self sign-up requests of engineers and architects (Permit360 Pro workspace only). */
function Signups({ toast, onChange }: { toast: (m: string, bad?: boolean) => void; onChange: () => void }) {
  const [d, setD] = useState<{ mode: string; items: SignupRow[] } | null>(null), [busy, setBusy] = useState(false)
  const load = () => api.get<any>('/api/signups').then(setD).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [])
  const act = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true)
    try { await fn(); toast(ok); await load(); onChange() } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  if (!d) return null
  const modeHe = d.mode === 'open' ? 'פתוחה — החשבון נפתח לאחר אימות הדוא״ל' : d.mode === 'approval' ? 'באישור מנהל — לאחר אימות הדוא״ל' : 'סגורה'
  return <div className="card" style={{ padding: 0, overflowX: 'auto', marginBottom: 12 }}>
    <div style={{ padding: '10px 14px' }}><b>בקשות הרשמה</b> <span className="small muted">הרשמה עצמית: {modeHe}</span></div>
    <table><thead><tr><th>שם</th><th>שם משתמש</th><th>דוא״ל</th><th>תחום</th><th>רישיון / ארגון</th><th>מצב</th><th /></tr></thead><tbody>
      {d.items.map(r => <tr key={r.username}>
        <td><b>{r.display_name}</b><div className="small muted">{fmtDate(r.requested_at)}</div></td>
        <td className="ltr">{r.username}</td><td className="ltr">{r.email}</td><td>{r.profession_he}</td>
        <td className="small">{[r.license_number, r.organization].filter(Boolean).join(' · ') || '—'}</td>
        <td>{r.state === 'APPROVAL_PENDING' ? <span className="chip warn">ממתין לאישור</span> : <span className="chip outline">ממתין לאימות דוא״ל</span>}</td>
        <td className="user-actions">
          {r.state === 'APPROVAL_PENDING' && <button className="sm primary" disabled={busy} onClick={() => act(() => api.post(`/api/signups/${r.username}/approve`), 'החשבון אושר ונשלחה הודעה')}>אישור</button>}
          <button className="sm" disabled={busy} onClick={() => { const reason = prompt(`לדחות את בקשת ${r.display_name}? הערה למבקש (לא חובה):`); if (reason !== null) act(() => api.post(`/api/signups/${r.username}/reject`, { reason }), 'הבקשה נדחתה') }}>דחייה</button>
        </td></tr>)}
      {!d.items.length && <tr><td colSpan={7} className="empty">אין בקשות ממתינות</td></tr>}
    </tbody></table>
  </div>
}

export default function Users() {
  const { me, toast } = useApp()
  const [rows, setRows] = useState<Row[]>([]), [roles, setRoles] = useState<{ id: string; label_he: string; tier?: string; tier_he?: string }[]>([])
  const [mode, setMode] = useState<'' | 'new' | 'member'>(''), [busy, setBusy] = useState(false)
  const [f, setF] = useState({ username: '', display_name: '', role: 'reviewer', password: '' })
  const [reset, setReset] = useState<Row | null>(null), [pw, setPw] = useState(''), [uname, setUname] = useState('')
  const load = () => api.get<any>('/api/users/manage').then(d => { setRows(d.users.filter((u: Row) => !PENDING.includes(u.signup_state ?? ''))); setRoles(d.roles) }).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [])
  const act = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true)
    try { await fn(); toast(ok); await load(); return true } catch (e: any) { toast(e.message, true); return false } finally { setBusy(false) }
  }
  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    const done = mode === 'new'
      ? await act(() => api.post('/api/users', f), 'המשתמש נוצר — בכניסה הראשונה יתבקש לבחור סיסמה')
      : await act(() => api.post('/api/users/members', { username: f.username, role: f.role }), 'המשתמש צורף לרשות')
    if (done) { setMode(''); setF({ username: '', display_name: '', role: 'reviewer', password: '' }) }
  }
  const doReset = async (e: React.FormEvent) => {
    e.preventDefault()
    if (await act(() => api.post(`/api/users/${reset!.id}/password`, { password: pw, username: reset!.login === 'none' ? uname : undefined }), 'הסיסמה אופסה — המשתמש יתבקש להחליפה')) { setReset(null); setPw(''); setUname('') }
  }
  const fmt = (s: string | null) => s ? new Date(s).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' }) : '—'
  return <>
    <div className="page-head"><div><h1>משתמשים</h1><p>משתמשי הרשות, תפקידים והרשאות כניסה. משתמש מרשות אחרת מקבל כאן תפקיד; הכניסה שלו מנוהלת ברשות הבית שלו.</p></div>
      <span className="spacer" />
      <button className={mode === 'new' ? 'primary' : ''} onClick={() => setMode(mode === 'new' ? '' : 'new')}>משתמש חדש</button>
      <button className={mode === 'member' ? 'primary' : ''} onClick={() => setMode(mode === 'member' ? '' : 'member')}>צירוף משתמש מרשות אחרת</button>
    </div>
    {me?.workspace && <Signups toast={toast} onChange={load} />}
    {mode && <form className="card user-form" onSubmit={add}>
      <label>שם משתמש<input dir="ltr" required value={f.username} onChange={e => setF({ ...f, username: e.target.value })} placeholder="first.last" autoComplete="off" /></label>
      {mode === 'new' && <label>שם מלא<input required maxLength={200} value={f.display_name} onChange={e => setF({ ...f, display_name: e.target.value })} /></label>}
      <label>תפקיד<select value={f.role} onChange={e => setF({ ...f, role: e.target.value })}>{roleOptions(roles)}</select></label>
      {mode === 'new' && <label>סיסמה ראשונית<input type="password" dir="ltr" required minLength={10} value={f.password} onChange={e => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></label>}
      <button className="primary" disabled={busy}>{mode === 'new' ? 'יצירה' : 'צירוף'}</button>
      <span className="small muted">{mode === 'new' ? 'לפחות 10 תווים. המשתמש יחליף אותה בכניסה הראשונה.' : 'שם המשתמש שלו ברשות הבית.'}</span>
    </form>}
    <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
      <table><thead><tr><th>שם</th><th>שם משתמש</th><th>תפקיד</th><th>כניסה</th><th>כניסה אחרונה</th><th></th></tr></thead><tbody>
        {rows.map(u => { const self = u.id === me?.id; return <tr key={u.id} className={u.active ? '' : 'muted'}>
          <td><b>{u.display_name}</b>{self && <span className="chip outline" style={{ marginInlineStart: 6 }}>את/ה</span>}{u.kind === 'member' && <div className="small muted">מרשות אחרת</div>}</td>
          <td className="ltr">{u.username ?? '—'}</td>
          <td><select aria-label={`תפקיד — ${u.display_name}`} value={u.role} disabled={self || busy} onChange={e => act(() => api.patch(`/api/users/${u.id}`, { role: e.target.value }), 'התפקיד עודכן')}>{roleOptions(roles)}</select></td>
          <td>{u.kind === 'member' ? <span className="chip outline">ברשות הבית</span>
            : u.login === 'none' ? <span className="chip outline">ללא כניסה</span>
            : u.login === 'legacy' ? <span className="chip outline">מוגדר בשרת</span>
            : !u.active ? <span className="chip bad">מושבת</span>
            : u.must_change ? <span className="chip warn">ממתין להחלפת סיסמה</span> : <span className="chip ok">פעיל</span>}</td>
          <td className="small">{fmt(u.last_login_at)}</td>
          <td className="user-actions">{!self && u.kind === 'home' && u.login !== 'legacy' && <button className="sm" disabled={busy} onClick={() => { setReset(u); setPw(''); setUname('') }}>{u.login === 'none' ? 'הגדרת כניסה' : 'איפוס סיסמה'}</button>}
            {!self && u.kind === 'home' && u.login === 'db' && <button className="sm" disabled={busy} onClick={() => act(() => api.post(`/api/users/${u.id}/active`, { active: !u.active }), u.active ? 'המשתמש הושבת' : 'המשתמש הופעל')}>{u.active ? 'השבתה' : 'הפעלה'}</button>}
            {!self && u.kind === 'member' && <button className="sm" disabled={busy} onClick={() => { if (confirm(`להסיר את ${u.display_name} מהרשות?`)) act(() => api.del(`/api/users/${u.id}/membership`), 'המשתמש הוסר מהרשות') }}>הסרה מהרשות</button>}</td>
        </tr> })}
        {!rows.length && <tr><td colSpan={6} className="empty">טוען…</td></tr>}
      </tbody></table>
    </div>
    {reset && <div className="modal-back" role="dialog" aria-modal="true" onClick={e => { if (e.target === e.currentTarget) setReset(null) }}>
      <form className="login" onSubmit={doReset}>
        <h1>{reset.login === 'none' ? 'הגדרת כניסה' : 'איפוס סיסמה'}</h1>
        <div className="hint">{reset.display_name} — סיסמה זמנית; בכניסה הבאה יתבקש לבחור סיסמה חדשה. חיבורים פתוחים שלו ינותקו.</div>
        {reset.login === 'none' && <label className="f">שם משתמש<input dir="ltr" required value={uname} onChange={e => setUname(e.target.value)} autoComplete="off" /></label>}
        <label className="f">סיסמה זמנית<input type="password" dir="ltr" required minLength={10} value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password" autoFocus /></label>
        <button className="primary" disabled={busy}>שמירה</button>
        <button type="button" onClick={() => setReset(null)}>ביטול</button>
      </form></div>}
  </>
}
