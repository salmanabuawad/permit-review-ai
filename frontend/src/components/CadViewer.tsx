import { useMemo, useRef, useState } from 'react'
import { Finding, STATUS_HE } from '../api'

// Minimal WKT parser for the overlay geometries returned by the backend (metres).
type Ring = [number, number][]
type Geom = { type: 'poly' | 'line'; rings: Ring[] }

function parseCoords(s: string): Ring {
  return s.trim().split(',').map(p => p.trim().split(/\s+/).map(Number) as [number, number])
}
export function parseWkt(wkt: string): Geom[] {
  const t = wkt.trim()
  if (t.startsWith('POLYGON')) {
    const rings = [...t.matchAll(/\(([^()]+)\)/g)].map(m => parseCoords(m[1]))
    return [{ type: 'poly', rings }]
  }
  if (t.startsWith('MULTIPOLYGON') || t.startsWith('GEOMETRYCOLLECTION')) {
    return [...t.matchAll(/\(\(([^()]+)\)/g)].map(m => ({ type: 'poly' as const, rings: [parseCoords(m[1])] }))
  }
  if (t.startsWith('LINESTRING')) {
    const m = t.match(/\(([^()]+)\)/)
    return m ? [{ type: 'line', rings: [parseCoords(m[1])] }] : []
  }
  return []
}

export const ROLE_STYLE: Record<string, { color: string; label: string; dash?: string; fill?: string }> = {
  PLOT_BOUNDARY: { color: '#1f3b73', label: 'גבול מגרש' },
  BUILDING_LINE: { color: '#2e7dd7', label: 'קו בניין', dash: '0.4 0.25' },
  EXISTING: { color: '#7d8798', label: 'קיים', fill: 'rgba(125,135,152,.10)' },
  PROPOSED: { color: '#0a7f4f', label: 'מוצע', fill: 'rgba(10,127,79,.12)' },
  BALCONY: { color: '#b36b00', label: 'מרפסת', fill: 'rgba(179,107,0,.10)' },
  SUKKAH: { color: '#00838f', label: 'סוכה', fill: 'rgba(0,131,143,.12)' },
  ROOF_ROOM: { color: '#6a3fb5', label: 'חדר גג', fill: 'rgba(106,63,181,.12)' },
  ROOF_EDGE_FRONT: { color: '#c2185b', label: 'שפת גג — חזית' },
}

interface Props { geo: any; loading?: boolean; findings: Finding[]; selected: string | null; onSelect: (id: string) => void }

export default function CadViewer({ geo, loading, findings, selected, onSelect }: Props) {
  const [view, setView] = useState<{ k: number; dx: number; dy: number }>({ k: 1, dx: 0, dy: 0 })
  const drag = useRef<{ x: number; y: number } | null>(null)
  const [hover, setHover] = useState<string | null>(null)

  const overlays = useMemo(() => findings
    .filter(f => f.overlay_wkt && (f.status === 'FAIL' || f.status === 'UNCERTAIN' || f.id === selected))
    .map(f => ({ f, geoms: parseWkt(f.overlay_wkt!) })), [findings, selected])

  const bbox = useMemo(() => {
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
    const eat = (x: number, y: number) => { minx = Math.min(minx, x); miny = Math.min(miny, y); maxx = Math.max(maxx, x); maxy = Math.max(maxy, y) }
    for (const ft of geo?.features ?? []) {
      const g = ft.geometry
      const coords: number[][] = g.type === 'Polygon' ? g.coordinates.flat() : g.type === 'LineString' ? g.coordinates : []
      coords.forEach(c => eat(c[0], c[1]))
    }
    overlays.forEach(o => o.geoms.forEach(g => g.rings.flat().forEach(([x, y]) => eat(x, y))))
    if (!isFinite(minx)) return null
    const pad = Math.max(maxx - minx, maxy - miny) * 0.06 + 0.5
    return { minx: minx - pad, miny: miny - pad, w: maxx - minx + 2 * pad, h: maxy - miny + 2 * pad, maxy: maxy + pad }
  }, [geo, overlays])

  if (!bbox) return <div className="viewer"><div className="empty">{loading ? 'טוען תשריט…'
    : 'לא הוגש שרטוט CAD מנותח (DXF/DWG) — אין תצוגת תשריט'}</div></div>

  // CAD Y axis points up; SVG Y points down -> flip with (maxy - y). Drawing stays geometrically true (not mirrored for RTL).
  const P = (x: number, y: number) => `${x.toFixed(3)},${(bbox.maxy - y).toFixed(3)}`
  const path = (rings: number[][][], close: boolean) => rings.map(r => 'M' + r.map(c => P(c[0], c[1])).join('L') + (close ? 'Z' : '')).join(' ')
  const vb = (() => {
    const w = bbox.w / view.k, h = bbox.h / view.k
    const cx = bbox.minx + bbox.w / 2 - view.dx, cy = bbox.h / 2 - view.dy
    return `${cx - w / 2} ${cy - h / 2} ${w} ${h}`
  })()
  const sw = Math.max(bbox.w, bbox.h) / 450 / view.k

  return (
    <div className="viewer">
      <div className="tools no-print">
        <button className="sm" onClick={() => setView(v => ({ ...v, k: v.k * 1.4 }))} aria-label="הגדלה">+</button>
        <button className="sm" onClick={() => setView(v => ({ ...v, k: v.k / 1.4 }))} aria-label="הקטנה">−</button>
        <button className="sm" onClick={() => setView({ k: 1, dx: 0, dy: 0 })}>התאם</button>
      </div>
      <svg viewBox={vb} preserveAspectRatio="xMidYMid meet" role="img" aria-label="תצוגת תשריט עם סימון ממצאים"
        onWheel={e => { const f = e.deltaY < 0 ? 1.15 : 1 / 1.15; setView(v => ({ ...v, k: Math.min(40, Math.max(0.3, v.k * f)) })) }}
        onMouseDown={e => { drag.current = { x: e.clientX, y: e.clientY } }}
        onMouseUp={() => { drag.current = null }} onMouseLeave={() => { drag.current = null }}
        onMouseMove={e => {
          if (!drag.current) return
          const el = e.currentTarget.getBoundingClientRect()
          const scale = (bbox.w / view.k) / el.width
          const ddx = (e.clientX - drag.current.x) * scale, ddy = (e.clientY - drag.current.y) * scale
          drag.current = { x: e.clientX, y: e.clientY }
          setView(v => ({ ...v, dx: v.dx + ddx, dy: v.dy + ddy }))
        }}>
        {(geo?.features ?? []).map((ft: any, i: number) => {
          const st = ROLE_STYLE[ft.properties.role] ?? { color: '#a0aec0', label: ft.properties.layer }
          const g = ft.geometry
          const d = g.type === 'Polygon' ? path(g.coordinates, true) : g.type === 'LineString' ? path([g.coordinates], false) : ''
          return <path key={i} d={d} fill={g.type === 'Polygon' ? st.fill ?? 'none' : 'none'} stroke={st.color}
            strokeWidth={sw * (ft.properties.role === 'ROOF_EDGE_FRONT' ? 2.2 : 1.3)} strokeDasharray={st.dash ? st.dash.split(' ').map(Number).map(n => n).join(' ') : undefined}
            onMouseEnter={() => setHover(`${st.label} · שכבה ${ft.properties.layer}${ft.properties.via_block ? ' · בלוק ' + ft.properties.via_block : ''}`)}
            onMouseLeave={() => setHover(null)} />
        })}
        {overlays.map(({ f, geoms }) => geoms.map((g, j) => (
          <path key={f.id + j} d={path(g.rings, g.type === 'poly')}
            fill={g.type === 'poly' ? (f.status === 'FAIL' ? 'rgba(180,35,24,.35)' : 'rgba(215,154,0,.30)') : 'none'}
            stroke={f.status === 'FAIL' ? '#b42318' : '#c58a00'} strokeWidth={sw * (f.id === selected ? 3.2 : 2)}
            style={{ cursor: 'pointer' }} onClick={() => onSelect(f.id)}
            onMouseEnter={() => setHover(`${STATUS_HE[f.status]}: ${f.title_he}`)} onMouseLeave={() => setHover(null)} />
        )))}
        {/* 5 m scale bar */}
        <g>
          <line x1={bbox.minx + bbox.w * 0.04} x2={bbox.minx + bbox.w * 0.04 + 5} y1={bbox.h * 0.97} y2={bbox.h * 0.97} stroke="#12233d" strokeWidth={sw * 2} />
          <text x={bbox.minx + bbox.w * 0.04 + 5.4} y={bbox.h * 0.975} fontSize={bbox.h * 0.025} fill="#12233d" direction="ltr">5 m</text>
        </g>
      </svg>
      {hover && <div className="hint">{hover}</div>}
      <div className="legend">
        {Object.entries(ROLE_STYLE).filter(([r]) => (geo?.features ?? []).some((f: any) => f.properties.role === r)).map(([r, s]) => (
          <span key={r}><i style={{ background: s.color }} />{s.label}</span>
        ))}
        <span><i style={{ background: '#b42318', height: 8 }} />אי-התאמה</span>
        <span><i style={{ background: '#d79a00', height: 8 }} />דורש בדיקה</span>
        <span className="muted">יחידות: מטר · קואורדינטות שרטוט מקומיות</span>
      </div>
    </div>
  )
}
