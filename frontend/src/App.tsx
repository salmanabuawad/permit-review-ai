import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, getUser, setUser } from './api'
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

export interface Me { id: string; tenant_id: string; role: string; role_he: string; display_name: string; permissions: string[] }
interface Ctx { me: Me | null; meta: any; can: (p: string) => boolean; toast: (m: string, err?: boolean) => void }
const AppCtx = createContext<Ctx>({ me: null, meta: null, can: () => false, toast: () => {} })
export const useApp = () => useContext(AppCtx)

const NAV = [
  { to: '/', label: 'לוח בקרה', icon: 'dashboard', end: true },
  { to: '/cases', label: 'תיקי בקשות', icon: 'files' },
  { to: '/rules', label: 'מאגר כללים', icon: 'rules', end: true },
  { to: '/rules/sources', label: 'סריקת מקורות', icon: 'radar' },
  { to: '/sources', label: 'מקורות ובסיס ידע', icon: 'database' },
  { to: '/ai', label: 'הגדרות AI', icon: 'brain' },
  { to: '/integrations', label: 'ממשקים', icon: 'links', tag: 'מתוכנן' },
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
  shield: 'M12 2 4 5v6c0 5 3 8 8 11 5-3 8-6 8-11V5z M9 12l2 2 4-4',
}
function NavIcon({ name }: { name: string }) {
  return <svg className="nav-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round"><path d={ICON_PATHS[name]} /></svg>
}

// Name shown in the sidebar, top bar and browser tab — follows the signed-in user's municipality.
const ORG: Record<string, { short: string; mark: string; org: string; unit: string }> = {
  'hof-ashkelon': { short: 'חוף אשקלון', mark: 'ח', org: 'הוועדה המקומית לתכנון ובנייה חוף אשקלון', unit: 'הוועדה המקומית לתכנון ובנייה' },
  'bnei-brak': { short: 'בני ברק', mark: 'ב', org: 'עיריית בני ברק', unit: 'מינהל ההנדסה' },
}
const DEFAULT_ORG = 'hof-ashkelon'

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [meta, setMeta] = useState<any>(null)
  const [userId] = useState(getUser())
  const [mobileOpen, setMobileOpen] = useState(false)
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null)

  const toast = useCallback((text: string, err = false) => {
    setMsg({ text, err })
    window.setTimeout(() => setMsg(null), 4200)
  }, [])

  useEffect(() => {
    api.get<any>('/api/meta').then(setMeta)
  }, [])
  useEffect(() => {
    setUser(userId)
    api.get<Me>('/api/me').then(setMe).catch(() => setMe(null))
  }, [userId])

  const can = (p: string) => !!me?.permissions.includes(p)
  const isDemo = me?.tenant_id === 'demo'
  const org = ORG[me?.tenant_id || DEFAULT_ORG] || ORG[DEFAULT_ORG]
  useEffect(() => { document.title = `בדיקת היתרי בנייה — ${isDemo ? 'סביבת הדגמה' : org.short}` }, [org, isDemo])

  return (
    <AppCtx.Provider value={{ me, meta, can, toast }}>
      <div className="app">
        {mobileOpen && <button className="mobile-overlay" aria-label="סגירת תפריט" onClick={() => setMobileOpen(false)} />}
        <aside className={'sidebar' + (mobileOpen ? ' mobile-open' : '')}>
          <div className="brand-lockup">
            <div className="brand-mark" aria-hidden="true">{org.mark}</div>
            <div><strong>מערכת רישוי חכמה</strong><small>{org.short} · מערכת תומכת החלטה</small></div>
          </div>
          <div className="sidebar-section-label">סביבת עבודה</div>
          <nav aria-label="ניווט ראשי">
            {NAV.map(n => (
              <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setMobileOpen(false)}>
                <NavIcon name={n.icon} /><span className="nav-label">{n.label}</span>{n.tag && <span className="tag">{n.tag}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-footer"><div className="sidebar-footer-dot" /> פיילוט · מערכת תומכת החלטה<small>גרסה ראשונית</small></div>
        </aside>
        <div className="main">
          {isDemo && (
            <div className="demo-banner" role="note">
              סביבת הדגמה — כל התיקים, הכתובות והאנשים פיקטיביים. כללי "הדגמה" מבוססים על תכנית DEMO/1 שאינה קיימת.
            </div>
          )}
          <header className="topbar">
            <button className="mobile-menu" aria-label="פתיחת תפריט" onClick={() => setMobileOpen(true)}>☰</button>
            <div className="topbar-location"><span className="topbar-eyebrow">סביבת עבודה / {org.org}</span><strong>{isDemo ? 'סביבת הדגמה' : org.unit}</strong></div>
            <span className="spacer" />
            <span className="topbar-policy"><span className="live-dot" /> כל תוצר הוא המלצה בלבד — ההחלטה בסמכות בעל תפקיד מוסמך</span>
            <span className="small muted">משתמש: {me?.display_name ?? 'מנהל מערכת'}</span>
          </header>
          <main className="content" key={userId}>
            {me && meta ? (
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/cases" element={<Cases />} />
                <Route path="/cases/import" element={<ImportCases />} />
                <Route path="/cases/:id" element={<CaseView />} />
                <Route path="/rules" element={<Rules />} />
                <Route path="/rules/sources" element={<SourceMonitor />} />
                <Route path="/sources" element={<Sources />} />
                <Route path="/ai" element={<AISettings />} />
                <Route path="/integrations" element={<Integrations />} />
                <Route path="/audit" element={<Audit />} />
              </Routes>
            ) : <div className="empty">טוען…</div>}
          </main>
        </div>
      </div>
      {msg && <div className={'toast' + (msg.err ? ' err' : '')} role="status">{msg.text}</div>}
    </AppCtx.Provider>
  )
}
