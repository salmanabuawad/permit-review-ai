import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, getUser, setUser } from './api'
import Dashboard from './pages/Dashboard'
import Cases from './pages/Cases'
import CaseView from './pages/CaseView'
import Rules from './pages/Rules'
import Sources from './pages/Sources'
import AISettings from './pages/AISettings'
import Integrations from './pages/Integrations'
import Audit from './pages/Audit'

export interface Me { id: string; tenant_id: string; role: string; role_he: string; display_name: string; permissions: string[] }
interface Ctx { me: Me | null; meta: any; can: (p: string) => boolean; toast: (m: string, err?: boolean) => void }
const AppCtx = createContext<Ctx>({ me: null, meta: null, can: () => false, toast: () => {} })
export const useApp = () => useContext(AppCtx)

const NAV = [
  { to: '/', label: 'לוח בקרה', end: true },
  { to: '/cases', label: 'תיקי בקשות' },
  { to: '/rules', label: 'מאגר כללים' },
  { to: '/sources', label: 'מקורות ובסיס ידע' },
  { to: '/ai', label: 'הגדרות AI' },
  { to: '/integrations', label: 'ממשקים', tag: 'מתוכנן' },
  { to: '/audit', label: 'יומן ביקורת' },
]

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [meta, setMeta] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [userId, setUserId] = useState(getUser())
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null)

  const toast = useCallback((text: string, err = false) => {
    setMsg({ text, err })
    window.setTimeout(() => setMsg(null), 4200)
  }, [])

  useEffect(() => {
    api.get<any>('/api/meta').then(setMeta)
    api.get<any[]>('/api/users').then(setUsers)
  }, [])
  useEffect(() => {
    setUser(userId)
    api.get<Me>('/api/me').then(setMe).catch(() => setMe(null))
  }, [userId])

  const can = (p: string) => !!me?.permissions.includes(p)
  const isDemo = me?.tenant_id === 'demo'

  return (
    <AppCtx.Provider value={{ me, meta, can, toast }}>
      <div className="app">
        <aside className="sidebar">
          <div className="logo">
            בדיקת היתרי בנייה בסיוע AI
            <small>הוועדה המקומית בני ברק · פיילוט (POC)</small>
          </div>
          <nav aria-label="ניווט ראשי">
            {NAV.map(n => (
              <NavLink key={n.to} to={n.to} end={n.end}>
                {n.label}{n.tag && <span className="tag">{n.tag}</span>}
              </NavLink>
            ))}
          </nav>
        </aside>
        <div className="main">
          {isDemo && (
            <div className="demo-banner" role="note">
              סביבת הדגמה — כל התיקים, הכתובות והאנשים פיקטיביים. כללי "הדגמה" מבוססים על תכנית DEMO/1 שאינה קיימת.
            </div>
          )}
          <header className="topbar">
            <strong>{isDemo ? 'סביבת הדגמה' : 'עיריית בני ברק'}</strong>
            <span className="chip outline">כל תוצר הוא המלצה בלבד — ההחלטה בסמכות בעל תפקיד מוסמך</span>
            <span className="spacer" />
            <label className="small muted" htmlFor="user-switch">משתמש (הדגמה):</label>
            <select id="user-switch" value={userId} onChange={e => setUserId(e.target.value)}>
              {users.map(u => <option key={u.id} value={u.id}>{u.display_name} — {u.role_he}</option>)}
            </select>
          </header>
          <main className="content" key={userId}>
            {me && meta ? (
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/cases" element={<Cases />} />
                <Route path="/cases/:id" element={<CaseView />} />
                <Route path="/rules" element={<Rules />} />
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
