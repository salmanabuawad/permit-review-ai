import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Integrations() {
  const [items, setItems] = useState<any[]>([])
  useEffect(() => { api.get<any[]>('/api/integrations').then(setItems) }, [])
  return (
    <>
      <div className="page-head"><div><h1>ממשקים עתידיים</h1><p>המערכת עובדת כיום על קבצים, ללא ממשקים פעילים למערכות חיצוניות. הממשקים להלן מתוכננים.</p></div></div>
      <div className="grid k3">
        {items.map(i => (
          <div key={i.id} className="card">
            <div className="card-head"><h3>{i.name_he}</h3><span className="spacer" /><span className="chip planned">מתוכנן · שלב {i.stage}</span></div>
            <p className="small muted" style={{ margin: 0 }}>לא מחובר. מפרט הממשק, הרשאות ואישור אבטחה יידרשו מהרשות לפני פיתוח.</p>
            <button className="sm" disabled style={{ marginTop: 10 }}>חיבור (טרם זמין)</button>
          </div>
        ))}
      </div>
    </>
  )
}
