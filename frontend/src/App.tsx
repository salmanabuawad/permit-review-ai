import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { api, selectedAuthority, setAuthority, authorityColor } from './api'
import Authorities from './pages/Authorities'
import Dashboard from './pages/Dashboard'
import Cases from './pages/Cases'
import CaseView from './pages/CaseView'
import SourceMonitor from './pages/SourceMonitor'
import Rules from './pages/Rules'
import Sources from './pages/Sources'
import AISettings from './pages/AISettings'
import Integrations from './pages/Integrations'
import Audit from './pages/Audit'
import ImportCases from './pages/ImportCases'
import Login from './pages/Login'
import Landing from './pages/Landing'
import Learning from './pages/Learning'
import Users from './pages/Users'
import Committees from './pages/Committees'
import Architect from './pages/Architect'
import ProjectNew from './pages/ProjectNew'
import ApplyWizard from './pages/ApplyWizard'
import Tasks from './pages/Tasks'
import ChangePassword from './components/ChangePassword'

export interface Me { id: string; tenant_id: string; role: string; role_he: string; display_name: string; permissions: string[]; municipality_name?: string; is_demo?: boolean; username?: string | null; must_change_password?: boolean; tier?: string; tier_he?: string; superadmin?: boolean; workspace?: boolean }
interface Ctx { me: Me | null; meta: any; can: (p: string) => boolean; toast: (m: string, err?: boolean) => void }
const AppCtx = createContext<Ctx>({ me: null, meta: null, can: () => false, toast: () => {} })
export const useApp = () => useContext(AppCtx)

const NAV = [
  { to: '/authorities', label: 'בחירת רשות וניהול ידע', icon: 'database' },
  { to: '/', label: 'לוח בקרה', icon: 'dashboard', end: true },
  { to: '/tasks', label: 'משימות', icon: 'shield' },
  { to: '/cases', label: 'תיקי בקשות', icon: 'files' },
  { to: '/apply', label: 'הגשת בקשה להיתר', icon: 'files', end: true },
  { to: '/architect', label: 'בדיקה לפני הגשה', icon: 'rules' },
  { to: '/rules', label: 'מאגר כללים', icon: 'rules', end: true },
  { to: '/rules/sources', label: 'סריקת מקורות', icon: 'radar' },
  { to: '/learning', label: 'למידה מהחלטות', icon: 'brain' },
  { to: '/sources', label: 'מקורות ובסיס ידע', icon: 'database' },
  { to: '/committees', label: 'מאגר ועדות ארצי', icon: 'map' },
  { to: '/ai', label: 'הגדרות AI', icon: 'brain' },
  { to: '/integrations', label: 'ממשקים', icon: 'links', tag: 'מתוכנן' },
  { to: '/users', label: 'משתמשים', icon: 'users' },
  { to: '/audit', label: 'יומן ביקורת', icon: 'shield' },
]

const ICON_PATHS: Record<string, string> = {
  dashboard: 'M3 3h8v8H3z M13 3h8v5h-8z M13 10h8v11h-8z M3 13h8v8H3z',
  files: 'M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 17h8',
  rules: 'M5 4h14v16H5z M9 9h6 M9 13h6 M9 17h4',
  radar: 'M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0 M12 12m-5 0a5 5 0 1 0 10 0a5 5 0 1 0 -10 0 M12 12l6-6',
  database: 'M4 6c0-4 16-4 16 0s-16 4-16 0 M4 6v12c0 4 16 4 16 0V6 M4 12c0 4 16 4 16 0',
  brain: 'M12 3a4 4 0 0 0-7 3 4 4 0 0 0-1 7 4 4 0 0 0 3 7 4 4 0 0 0 5-2 M12 3a4 4 0 0 1 7 3 4 4 0 0 1 1 7 4 4 0 0 1-3 7 4 4 0 0 1-5-2 M12 3v16',
  links: 'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',
  users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M2 21v-1a7 7 0 0 1 14 0v1 M16 3.5a4 4 0 0 1 0 7.5 M18 14a6 6 0 0 1 4 6v1',
  map: 'M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z M9 4v14 M15 6v14',
  shield: 'M12 2 4 5v6c0 5 3 8 8 11 5-3 8-6 8-11V5z M9 12l2 2 4-4',
}
function NavIcon({ name }: { name: string }) {
  return <svg className="nav-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round"><path d={ICON_PATHS[name]} /></svg>
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [meta, setMeta] = useState<any>(null)
  const [workspaces,setWorkspaces]=useState<any[]>([])
  const [mobileOpen, setMobileOpen] = useState(false)
  const [needLogin, setNeedLogin] = useState(false)
  const [pwOpen, setPwOpen] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null)

  const toast = useCallback((text: string, err = false) => {
    setMsg({ text, err })
    window.setTimeout(() => setMsg(null), 4200)
  }, [])

  useEffect(() => {
    api.get<any>('/api/meta').then(setMeta).catch(e => { if (e.status !== 401) setLoadError(e.message) })
  }, [])
  useEffect(() => {
    api.get<Me>('/api/me').then(m=>{setMe(m); if (!selectedAuthority()) setAuthority(m.tenant_id); api.get<any>('/api/authorities').then(r=>setWorkspaces(r.authorities)).catch(e=>setLoadError(e.message))}).catch(e => { setMe(null); if (e?.status === 401) setNeedLogin(true); else if (e?.status===403 && selectedAuthority()) {setAuthority(''); window.location.reload()} else setLoadError(e.message) })
  }, [])
  useEffect(() => {
    const on = () => setNeedLogin(true)
    window.addEventListener('bbp-unauth', on)
    return () => window.removeEventListener('bbp-unauth', on)
  }, [])
  const logout = () => { api.post('/api/auth/logout').finally(() => {setAuthority(''); window.location.reload()}) }

  const can = (p: string) => !!me?.permissions.includes(p)
  const isDemo = me?.is_demo ?? me?.tenant_id === 'demo'
  const org = me?.municipality_name || me?.tenant_id || 'סביבת רישוי'
  useEffect(() => { if (me) document.title = `${isDemo ? 'סביבת הדגמה' : org} — בדיקת היתרי בנייה` }, [me, org, isDemo])

  if (needLogin) {
    const q = new URLSearchParams(window.location.search)
    return window.location.pathname === '/login' || q.has('signup') ? <Login /> : <Landing />
  }
  if (me?.must_change_password) return <ChangePassword forced onDone={() => window.location.assign('/')} />

  return (
    <AppCtx.Provider value={{ me, meta, can, toast }}>
      <div className="app" style={{ ['--auth' as any]: isDemo ? '#d99a2b' : authorityColor(me?.tenant_id) }}>
        {mobileOpen && <button className="mobile-overlay" aria-label="סגירת תפריט" onClick={() => setMobileOpen(false)} />}
        <aside className={'sidebar' + (mobileOpen ? ' mobile-open' : '')}>
          <div className="brand-lockup">
            <div className="brand-mark" aria-hidden="true">⌑</div>
            <div><strong>מערכת רישוי חכמה</strong><small>{org} · מערכת תומכת החלטה</small></div>
          </div>
          <div className="sidebar-section-label">סביבת עבודה</div>
          <nav aria-label="ניווט ראשי">
            {NAV.filter(n => n.to === '/' ? can('dashboard.read') : n.to === '/audit' ? can('audit.read') : n.to === '/ai' ? can('ai.configure') : n.to === '/rules/sources' ? can('source.crawl') : n.to === '/learning' ? (can('learning.manage') || can('finding.decide')) : n.to === '/users' ? can('user.manage') : n.to === '/committees' ? can('source.crawl') : n.to === '/architect' || n.to === '/apply' ? can('design.create') : n.to === '/tasks' ? can('case.read') && !can('design.create') || can('case.assign') : true).map(n => (
              <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setMobileOpen(false)}>
                <NavIcon name={n.icon} /><span className="nav-label">{n.label}</span>{n.tag && <span className="tag">{n.tag}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-footer"><div className="sidebar-footer-dot" /> פיילוט · מערכת תומכת החלטה<small>מערכת רב־רשותית</small></div>
        </aside>
        <div className="main">
          {isDemo && (
            <div className="demo-banner" role="note">
              סביבת הדגמה — כל התיקים, הכתובות והאנשים פיקטיביים. כללי "הדגמה" מבוססים על תכנית DEMO/1 שאינה קיימת.
            </div>
          )}
          <header className="topbar">
            <button className="mobile-menu" aria-label="פתיחת תפריט" onClick={() => setMobileOpen(true)}>☰</button>
            <div className={'authority-badge' + (isDemo ? ' demo' : '')}>
              <span className="authority-label">{isDemo ? 'סביבת הדגמה' : 'רשות פעילה'}</span>
              {me && workspaces.length > 1
                ? <select aria-label="בחירת רשות" value={me.tenant_id} onChange={e=>{setAuthority(e.target.value);window.location.assign('/')}}>{workspaces.map(a=><option key={a.id} value={a.id}>{a.name_he}</option>)}</select>
                : <strong>{org}</strong>}
            </div>
            <span className="spacer" />
            <span className="topbar-policy"><span className="live-dot" /> כל תוצר הוא המלצה בלבד — ההחלטה בסמכות בעל תפקיד מוסמך</span>
            <button className="link-btn small" title="החלפת סיסמה" onClick={() => setPwOpen(true)}>{me?.display_name ?? '—'}</button>{me?.tier_he && <span className={'chip ' + (me.superadmin ? 'bad' : 'outline')} title={me.role_he} style={{ marginInlineStart: 4 }}>{me.tier_he}</span>}
            <button className="sm" onClick={logout}>יציאה</button>
          </header>
          {pwOpen && <ChangePassword onDone={() => { setPwOpen(false); toast('הסיסמה הוחלפה') }} onCancel={() => setPwOpen(false)} />}
          <main className="content">
            {me && meta ? (
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/login" element={<Navigate to="/" replace />} />
                <Route path="/authorities" element={<Authorities />} />
                <Route path="/learning" element={<Learning />} />
                <Route path="/cases" element={<Cases />} />
                <Route path="/cases/import" element={<ImportCases />} />
                <Route path="/cases/:id" element={<CaseView />} />
                <Route path="/rules" element={<Rules />} />
                <Route path="/rules/sources" element={<SourceMonitor />} />
                <Route path="/sources" element={<Sources />} />
                <Route path="/ai" element={<AISettings />} />
                <Route path="/integrations" element={<Integrations />} />
                <Route path="/audit" element={<Audit />} />
                <Route path="/users" element={<Users />} />
                <Route path="/committees" element={<Committees />} />
                <Route path="/architect" element={<Architect />} />
                <Route path="/projects/new" element={<ProjectNew />} />
                <Route path="/apply" element={<ApplyWizard />} />
                <Route path="/apply/:id" element={<ApplyWizard />} />
                <Route path="/tasks" element={<Tasks />} />
              </Routes>
            ) : loadError ? <div className="notice warn" role="alert">לא ניתן לטעון את סביבת העבודה: {loadError} <button onClick={() => window.location.reload()}>נסה שוב</button></div> : <div className="empty" role="status">טוען…</div>}
          </main>
        </div>
      </div>
      {msg && <div className={'toast' + (msg.err ? ' err' : '')} role="status">{msg.text}</div>}
    </AppCtx.Provider>
  )
}
