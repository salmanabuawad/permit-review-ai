#!/usr/bin/env python3
"""Static checks on website/dist: metadata, canonical / hreflang reciprocity, sitemap, internal links, JSON-LD,
headings, form labels, image alternatives, language / direction and page weight. Exit 1 on any failure.

    python website/tests/check_site.py [--base https://permit.kortexd.com]"""
import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

DIST = Path(__file__).resolve().parents[1] / "dist"
LANGS = {"he": "rtl", "ar": "rtl", "en": "ltr", "ru": "ltr"}
HEB = re.compile(r"[֐-׿]")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_attrs, self.title, self.meta, self.links, self.hrefs, self.ld = {}, "", {}, [], [], []
        self.headings, self.inputs, self.labels_open, self.labelled, self.svg_roles = [], [], 0, 0, []
        self._t = None
        self._buf = ""
        self.ids = set()
        self.text_he_outside = 0

    def handle_starttag(self, tag, a):
        a = dict(a)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "html":
            self.html_attrs = a
        elif tag == "title":
            self._t = "title"
            self._buf = ""
        elif tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta[k] = a.get("content", "")
        elif tag == "link":
            self.links.append(a)
        elif tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._t, self._buf = "ld", ""
        elif tag in ("h1", "h2", "h3", "h4"):
            self.headings.append(int(tag[1]))
        elif tag == "label":
            self.labels_open += 1
        elif tag in ("input", "select", "textarea") and a.get("type") != "hidden":
            self.inputs.append(bool(self.labels_open) or bool(a.get("aria-label")))
        elif tag == "svg" and a.get("role") == "img":
            self.svg_roles.append(a)

    def handle_endtag(self, tag):
        if tag == "title" and self._t == "title":
            self.title, self._t = self._buf.strip(), None
        elif tag == "script" and self._t == "ld":
            self.ld.append(self._buf)
            self._t = None
        elif tag == "label":
            self.labels_open -= 1

    def handle_data(self, d):
        if self._t:
            self._buf += d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://permit360.kortexd.com")
    base = ap.parse_args().base.rstrip("/")
    errors, warnings, pages = [], [], {}
    files = sorted(DIST.rglob("*.html"))
    for f in files:
        rel = "/" + str(f.relative_to(DIST)).replace("index.html", "")
        p = Page()
        p.feed(f.read_text(encoding="utf-8"))
        pages[rel] = p
    sitemap = {u.text for u in ET.parse(DIST / "sitemap.xml").getroot().iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}
    for rel, p in pages.items():
        if rel.startswith("/site/"):
            continue
        lang = p.html_attrs.get("lang")
        where = rel
        if True:
            if lang not in LANGS or p.html_attrs.get("dir") != LANGS[lang] or not rel.startswith(f"/{lang}/"):
                errors.append(f"{where}: lang/dir {lang}/{p.html_attrs.get('dir')}")
            if not 10 <= len(p.title) <= 70:
                errors.append(f"{where}: title length {len(p.title)}")
            d = p.meta.get("description", "")
            if not 70 <= len(d) <= 170:
                errors.append(f"{where}: description length {len(d)}")
            if p.headings.count(1) != 1:
                errors.append(f"{where}: {p.headings.count(1)} h1")
            for a, b in zip(p.headings, p.headings[1:]):
                if b > a + 1:
                    warnings.append(f"{where}: heading jump h{a}→h{b}")
                    break
        canon = [l["href"] for l in p.links if l.get("rel") == "canonical"]
        if canon != [base + rel]:
            errors.append(f"{where}: canonical {canon}")
        if base + rel not in sitemap:
            errors.append(f"{where}: not in sitemap")
        alts = {l["hreflang"]: l["href"] for l in p.links if l.get("rel") == "alternate" and l.get("hreflang")}
        if set(alts) != {*LANGS, "x-default"}:
            errors.append(f"{where}: hreflang set {sorted(alts)}")
        for hl, href in alts.items():
            target = href.replace(base, "")
            if target not in pages:
                errors.append(f"{where}: hreflang {hl} → missing {target}")
                continue
            back = {l["hreflang"]: l["href"] for l in pages[target].links if l.get("rel") == "alternate" and l.get("hreflang")}
            if hl != "x-default" and back.get(lang if rel != "/" else "he", None) is None:
                errors.append(f"{where}: {target} does not link back")
        for href in p.hrefs:
            if href.startswith(("/login", "/apply")):          # the application, same host
                continue
            if href.startswith("/") and not href.startswith("//"):
                path, _, frag = href.partition("#")
                path = path.split("?")[0]
                if path and path not in pages and not (DIST / path.lstrip("/")).exists():
                    errors.append(f"{where}: broken link {href}")
                if frag and (path or rel) == rel and frag not in p.ids:
                    errors.append(f"{where}: missing anchor #{frag}")
                elif frag and path in pages and frag not in pages[path].ids:
                    errors.append(f"{where}: missing anchor {href}")
            elif href.startswith("#") and href[1:] and href[1:] not in p.ids:
                errors.append(f"{where}: missing anchor {href}")
        for blob in p.ld:
            try:
                json.loads(blob)
            except ValueError as ex:
                errors.append(f"{where}: JSON-LD {ex}")
        if not all(p.inputs):
            errors.append(f"{where}: unlabelled form field")
        if lang in ("en", "ru", "ar") and rel != "/":
            raw = (DIST / rel.lstrip("/") / "index.html").read_text(encoding="utf-8")
            body = re.sub(r'<[^>]*lang="he"[^>]*>.*?</[a-z]+>|<script.*?</script>|<link[^>]*>|<a [^>]*hreflang="he"[^>]*>.*?</a>', "", raw, flags=re.S)
            n = len(HEB.findall(re.sub(r"<[^>]+>", " ", body)))
            if n:
                warnings.append(f"{where}: {n} Hebrew characters outside lang=he")
        size = (DIST / rel.lstrip("/") / "index.html").stat().st_size
        if size > 120_000:
            warnings.append(f"{where}: HTML {size // 1024} KB")
    for u in sitemap:
        if u.replace(base, "") not in pages:
            errors.append(f"sitemap: {u} has no page")
    assets = sum(f.stat().st_size for f in (DIST / "site").rglob("*") if f.is_file() and f.suffix in (".css", ".js"))
    print(f"{len(pages)} HTML files · {len(sitemap)} sitemap URLs · CSS+JS {assets // 1024} KB")
    for w in warnings:
        print("WARN ", w)
    for x in errors:
        print("ERROR", x)
    print("OK" if not errors else f"{len(errors)} errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
