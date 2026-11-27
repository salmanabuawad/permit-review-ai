"""SVG illustrations for the Permit360 website — architectural / cadastral linework, no stock imagery.
All text inside the drawings comes from the caller (localized); numbers are example data."""
from html import escape as e


def hero(t: dict, rtl: bool = False) -> str:
    """Isometric cadastral scene: parcel grid, the selected parcel, the planning-area boundary, a building massing
    with setback dimensions, and three floating data cards (example data)."""
    def tx(x0, x1, y, txt, size, fill, weight=None):
        """Card text: start-aligned at x0 (LTR) or end-aligned at x1 (RTL)."""
        w = f' font-weight="{weight}"' if weight else ""
        if rtl:
            return f'<text x="{x1}" y="{y}" text-anchor="start" direction="rtl" fill="{fill}" font-size="{size}"{w}>{e(txt)}</text>'
        return f'<text x="{x0}" y="{y}" fill="{fill}" font-size="{size}"{w}>{e(txt)}</text>'
    dot_x = 236 if rtl else 44
    return f"""<svg viewBox="0 0 640 520" role="img" aria-labelledby="hero-art-t" xmlns="http://www.w3.org/2000/svg" direction="ltr">
<title id="hero-art-t">{e(t['alt'])}</title>
<defs>
 <linearGradient id="hg-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0c2a40"/><stop offset="1" stop-color="#071a2b"/></linearGradient>
 <linearGradient id="hg-roof" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3e8494"/><stop offset="1" stop-color="#23596a"/></linearGradient>
 <linearGradient id="hg-wall-l" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b6274"/><stop offset="1" stop-color="#173f50"/></linearGradient>
 <linearGradient id="hg-wall-r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b4a5b"/><stop offset="1" stop-color="#0f3141"/></linearGradient>
 <pattern id="hg-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><path d="M0 0V8" stroke="#5fd6c8" stroke-opacity=".22" stroke-width="2"/></pattern>
 <filter id="hg-glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="6"/></filter>
</defs>
<rect width="640" height="520" rx="14" fill="url(#hg-sky)"/>
<g stroke="#5fd6c8" stroke-opacity=".09">{''.join(f'<path d="M{x} 0V520"/>' for x in range(0, 641, 32))}{''.join(f'<path d="M0 {y}H640"/>' for y in range(0, 521, 32))}</g>
<!-- cadastral blocks (isometric) -->
<g transform="translate(320 300)" fill="none" stroke="#7fb9c4" stroke-opacity=".38" stroke-width="1">
 <path d="M-300 0 0 -150 300 0 0 150Z" stroke-opacity=".5"/>
 <path d="M-240 -30 60 -180M-180 -60 120 -210M-120 -90 180 -240" stroke-opacity=".0"/>
 <path d="M-250 25 50 -125M-200 50 100 -100M-150 75 150 -75M-100 100 200 -50M-50 125 250 -25"/>
 <path d="M-250 -25 50 125M-200 -50 100 100M-150 -75 150 75M-100 -100 200 50M-50 -125 250 25"/>
</g>
<!-- planning-area boundary -->
<path class="draw" d="M70 330 290 200 470 250 560 330 330 455 150 420Z" fill="none" stroke="#5fd6c8" stroke-width="1.6" stroke-opacity=".75"/>
<!-- the selected parcel -->
<path d="M220 320 320 262 420 320 320 378Z" fill="url(#hg-hatch)" stroke="#5fd6c8" stroke-width="2"/>
<path d="M220 320 320 262 420 320 320 378Z" fill="#5fd6c8" fill-opacity=".08" filter="url(#hg-glow)"/>
<!-- setback envelope -->
<path d="M252 320 320 281 388 320 320 359Z" fill="none" stroke="#f1c46b" stroke-width="1.3" stroke-dasharray="4 4"/>
<!-- building massing -->
<g stroke="#9fd8df" stroke-width="1.1" stroke-linejoin="round">
 <path d="M268 318 320 288 372 318 320 348Z" fill="#1d4a5c"/>
 <path d="M268 318 320 348 320 262 268 232Z" fill="url(#hg-wall-l)"/>
 <path d="M320 348 372 318 372 232 320 262Z" fill="url(#hg-wall-r)"/>
 <path d="M268 232 320 202 372 232 320 262Z" fill="url(#hg-roof)"/>
 <path d="M268 289 320 319M268 261 320 291M320 319 372 289M320 291 372 261" stroke-opacity=".55"/>
 <g fill="#bde9ee" fill-opacity=".55" stroke="none">
  <path d="M278 302l12 7v12l-12-7Z M298 314l12 7v12l-12-7Z M278 274l12 7v12l-12-7Z M298 286l12 7v12l-12-7Z M278 246l12 7v12l-12-7Z M298 258l12 7v12l-12-7Z"/>
  <path d="M332 333l12-7v12l-12 7Z M352 321l12-7v12l-12 7Z M332 305l12-7v12l-12 7Z M352 293l12-7v12l-12 7Z M332 277l12-7v12l-12 7Z M352 265l12-7v12l-12 7Z"/>
 </g>
</g>
<!-- dimension lines -->
<g stroke="#f1c46b" stroke-width="1" fill="#f1c46b" font-family="Inter, Arial" font-size="11" font-weight="600">
 <path d="M372 318 388 320" /><path d="M380 336 398 346" /><text x="398" y="358" fill="#f1c46b" stroke="none">4.00 m</text>
 <path d="M240 210V196M240 203H264" /><text x="200" y="192" fill="#f1c46b" stroke="none">h 10.5 m</text>
</g>
<!-- floating cards -->
<g class="float" font-family="Inter, Heebo, 'Noto Sans Arabic', Arial">
 <rect x="22" y="26" width="236" height="96" rx="12" fill="#0e2d42" stroke="#2b5a6c"/>
 <circle cx="{dot_x}" cy="52" r="6" fill="#5fd6c8" class="pulse"/>
 {tx(58, 222, 56, t['card1_k'], 12, '#5fd6c8', 700)}
 {tx(40, 240, 84, t['card1_v'], 16, '#ffffff', 700)}
 {tx(40, 240, 106, t['card1_s'], 11.5, '#8fb3c0')}
</g>
<g class="float d2" font-family="Inter, Heebo, 'Noto Sans Arabic', Arial">
 <rect x="410" y="40" width="208" height="112" rx="12" fill="#0e2d42" stroke="#2b5a6c"/>
 {tx(428, 600, 66, t['card2_k'], 12, '#5fd6c8', 700)}
 <rect x="428" y="80" width="172" height="7" rx="3.5" fill="#1e4557"/><rect x="{472 if rtl else 428}" y="80" width="128" height="7" rx="3.5" fill="#5fd6c8"/>
 {tx(428, 600, 112, t['card2_a'], 13, '#ffffff')}
 {tx(428, 600, 134, t['card2_b'], 13, '#ffffff')}
</g>
<g class="float" font-family="Inter, Heebo, 'Noto Sans Arabic', Arial">
 <rect x="424" y="402" width="196" height="88" rx="12" fill="#0e2d42" stroke="#2b5a6c"/>
 {tx(442, 602, 428, t['card3_k'], 12, '#5fd6c8', 700)}
 <rect x="442" y="442" width="58" height="22" rx="11" fill="#173f30"/><text x="452" y="457" fill="#6fe0a4" font-size="11.5" font-weight="700">✓ 14</text>
 <rect x="506" y="442" width="52" height="22" rx="11" fill="#3e2a12"/><text x="516" y="457" fill="#f1c46b" font-size="11.5" font-weight="700">! 2</text>
 {tx(442, 602, 480, t['card3_s'], 11, '#8fb3c0')}
</g>
</svg>"""


def lookup_empty() -> str:
    return """<svg viewBox="0 0 120 90" aria-hidden="true" xmlns="http://www.w3.org/2000/svg"><g fill="none" stroke="#5fd6c8" stroke-width="1.4">
<path d="M8 50 60 20 112 50 60 80Z" stroke-opacity=".35"/><path d="M34 50 60 35 86 50 60 65Z" fill="#5fd6c8" fill-opacity=".12"/>
<path class="draw" d="M18 46 52 26 98 40 104 58 62 82 22 70Z"/><circle cx="60" cy="50" r="4" fill="#5fd6c8" class="pulse"/></g></svg>"""


ICONS = {
    "evidence": '<path d="M8 4h14l8 8v24H8z M22 4v8h8 M13 20h14 M13 26h14 M13 32h8" />',
    "people": '<circle cx="14" cy="13" r="5"/><circle cx="27" cy="15" r="4"/><path d="M4 33c1-6 5-9 10-9s9 3 10 9 M23 25c4 0 8 2 9 8"/>',
    "local": '<rect x="6" y="6" width="28" height="12" rx="3"/><rect x="6" y="22" width="28" height="12" rx="3"/><path d="M11 12h2 M11 28h2 M20 12h9 M20 28h9"/>',
    "israel": '<path d="M6 30 20 8l14 22z M20 8v22 M11 22h18"/>',
    "parcel": '<path d="M4 22 20 12l16 10-16 10z M12 22l8-5 8 5-8 5z"/>',
    "drawing": '<rect x="5" y="7" width="30" height="26" rx="2"/><path d="M11 27V14h11v13 M22 20h7v7 M9 31h22"/>',
    "shield": '<path d="M20 4 33 9v9c0 9-6 15-13 18C13 33 7 27 7 18V9z M14 19l4 4 8-8"/>',
    "law": '<path d="M20 5v28 M10 33h20 M8 12h24 M8 12l-4 10h8z M32 12l-4 10h8z"/>',
    "rights": '<rect x="7" y="9" width="26" height="24" rx="2"/><path d="M7 16h26 M15 16v17 M7 24h26"/>',
    "search": '<circle cx="17" cy="17" r="10"/><path d="M25 25l9 9"/>',
    "users": '<circle cx="20" cy="13" r="6"/><path d="M8 34c2-7 6-10 12-10s10 3 12 10"/>',
    "committee": '<path d="M5 16 20 7l15 9 M8 16v15 M16 16v15 M24 16v15 M32 16v15 M5 33h30"/>',
    "mail": '<rect x="5" y="9" width="30" height="22" rx="3"/><path d="m6 11 14 10 14-10"/>',
    "globe": '<circle cx="20" cy="20" r="14"/><path d="M6 20h28 M20 6c5 5 5 23 0 28 M20 6c-5 5-5 23 0 28"/>',
}


def icon(name: str, color: str = "#5fd6c8") -> str:
    return (f'<svg viewBox="0 0 40 40" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


def page_art(kind: str) -> str:
    """Compact technical drawing for a content page header."""
    base = '<svg viewBox="0 0 360 240" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" direction="ltr" fill="none" stroke-linecap="round" stroke-linejoin="round">'
    grid = '<g stroke="#5fd6c8" stroke-opacity=".08">' + "".join(f'<path d="M{x} 0V240"/>' for x in range(0, 361, 24)) + "".join(f'<path d="M0 {y}H360"/>' for y in range(0, 241, 24)) + "</g>"
    if kind in ("parcel", "committee", "rights"):
        body = ('<g stroke="#7fb9c4" stroke-opacity=".45"><path d="M30 130 180 45 330 130 180 215Z"/><path d="M80 158 230 73M130 186 280 101M55 102 205 187M105 74 255 159"/></g>'
                '<path class="draw" d="M40 140 170 60 300 100 320 150 190 220 60 190Z" stroke="#5fd6c8" stroke-width="1.6"/>'
                '<path d="M130 130 180 101 230 130 180 159Z" fill="#5fd6c8" fill-opacity=".18" stroke="#5fd6c8" stroke-width="2"/>'
                '<circle cx="180" cy="130" r="5" fill="#5fd6c8" class="pulse"/>')
        if kind == "rights":
            body += '<g stroke="#f1c46b" stroke-dasharray="4 4"><path d="M146 130 180 110 214 130 180 150Z"/></g><text x="222" y="168" fill="#f1c46b" font-family="Inter" font-size="12">4.00 m</text>'
    elif kind in ("drawing", "review"):
        body = ('<rect x="40" y="30" width="280" height="180" rx="6" stroke="#2b5a6c"/>'
                '<g stroke="#9fd8df" stroke-width="1.4"><path d="M90 170V80h120v90z M210 120h60v50h-60"/><path d="M90 125h120 M150 80v90" stroke-opacity=".5"/></g>'
                '<g stroke="#f1c46b"><path d="M90 190h120 M90 186v8 M210 186v8"/></g><text x="132" y="206" fill="#f1c46b" font-family="Inter" font-size="12">12.40 m</text>'
                '<rect x="206" y="116" width="68" height="58" stroke="#e36a74" stroke-width="2" stroke-dasharray="5 4"/>'
                '<circle cx="274" cy="116" r="9" fill="#e36a74"/><text x="270" y="120" fill="#fff" font-family="Inter" font-size="11" font-weight="700">!</text>')
    elif kind in ("shield", "local"):
        body = ('<g stroke="#2b5a6c"><rect x="70" y="60" width="140" height="34" rx="6"/><rect x="70" y="104" width="140" height="34" rx="6"/><rect x="70" y="148" width="140" height="34" rx="6"/></g>'
                '<g stroke="#5fd6c8"><path d="M84 77h4 M84 121h4 M84 165h4"/><path d="M100 77h90 M100 121h70 M100 165h80" stroke-opacity=".5"/></g>'
                '<path d="M270 70 300 82v22c0 22-14 35-30 42-16-7-30-20-30-42V82z" stroke="#5fd6c8" stroke-width="2" fill="#5fd6c8" fill-opacity=".1"/>'
                '<path d="M258 106l9 9 18-18" stroke="#5fd6c8" stroke-width="2.2"/><path class="draw" d="M210 121h28" stroke="#5fd6c8"/>')
    else:  # law / documents
        body = ('<g stroke="#2b5a6c" fill="#0e2d42"><rect x="110" y="40" width="150" height="180" rx="8"/><rect x="95" y="30" width="150" height="180" rx="8"/></g>'
                '<g stroke="#9fd8df" stroke-opacity=".6"><path d="M115 60h70 M115 80h110 M115 96h110 M115 112h90 M115 136h110 M115 152h100 M115 168h80"/></g>'
                '<path d="M112 128h126" stroke="#5fd6c8" stroke-width="2"/><rect x="108" y="122" width="134" height="26" rx="4" stroke="#5fd6c8" stroke-dasharray="4 4"/>'
                '<circle cx="262" cy="190" r="22" stroke="#5fd6c8" fill="#071a2b"/><path d="M252 190l7 7 13-13" stroke="#5fd6c8" stroke-width="2.2"/>')
    return base + grid + body + "</svg>"


def mini_map(cand_a: str, cand_b: str) -> str:
    """Two planning areas over a parcel (demo, step 2)."""
    return f"""<svg class="m-svg" viewBox="0 0 320 150" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" direction="ltr" font-family="Inter, Heebo, 'Noto Sans Arabic', Arial">
<path d="M10 20h170v110H10z" fill="#e6f5f2" stroke="#16a79f" stroke-dasharray="5 4"/><path d="M180 20h130v110H180z" fill="#eef2f6" stroke="#8ba3b5" stroke-dasharray="5 4"/>
<path d="M120 55h56v50h-56z" fill="#16a79f" fill-opacity=".35" stroke="#0b6f6b" stroke-width="2"/>
<text x="18" y="38" font-size="11" fill="#0b6f6b" font-weight="700">{e(cand_a)}</text><text x="188" y="38" font-size="11" fill="#5d7384">{e(cand_b)}</text>
<circle cx="148" cy="80" r="4" fill="#0b6f6b"/></svg>"""


def plan_drawing(t: dict, highlight: bool = True) -> str:
    """Site plan with plot boundary, building, setback lines and one marked finding (demo, authority steps 3–4)."""
    mark = ('<rect x="200" y="46" width="64" height="76" fill="none" stroke="#c2414b" stroke-width="2" stroke-dasharray="5 4"/>'
            '<circle cx="264" cy="46" r="9" fill="#c2414b"/><text x="261" y="50" fill="#fff" font-size="11" font-weight="700">!</text>') if highlight else ""
    return f"""<svg class="m-svg" viewBox="0 0 320 190" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" direction="ltr" font-family="Inter, Arial">
<path d="M20 20h280v150H20z" fill="#fbfcfd" stroke="#8ba3b5"/>
<path d="M48 44h216v100H48z" fill="none" stroke="#d9962b" stroke-dasharray="4 4"/>
<path d="M70 60h130v76H70z M200 60h60v62h-60z" fill="#e6f0f6" stroke="#12324a" stroke-width="1.6"/>
<path d="M135 60v76 M70 98h130" stroke="#12324a" stroke-opacity=".35"/>
<path d="M260 160h40 M260 156v8 M300 156v8" stroke="#d9962b"/><text x="262" y="182" font-size="10.5" fill="#8a5a10">{e(t['setback'])}</text>
<text x="74" y="154" font-size="10" fill="#5d7384">{e(t['layer'])}</text>{mark}</svg>"""
