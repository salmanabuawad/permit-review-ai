from pathlib import Path
from html import escape
from zipfile import ZipFile, ZIP_DEFLATED
import json

BASE = "https://permit360.kortexd.com"
ROOT = Path("Permit360_Landing_Page_Release")
ROOT.mkdir(exist_ok=True)

LANGS = {
    "he": {
        "dir": "rtl",
        "locale": "he_IL",
        "title": "Permit360 | \u05d4\u05db\u05e0\u05d4 \u05d5\u05d1\u05d3\u05d9\u05e7\u05ea \u05d1\u05e7\u05e9\u05d5\u05ea \u05dc\u05d4\u05d9\u05ea\u05e8 \u05d1\u05e0\u05d9\u05d9\u05d4 \u05d1\u05d9\u05e9\u05e8\u05d0\u05dc",
        "description": "\u05de\u05e2\u05e8\u05db\u05ea \u05d7\u05db\u05de\u05d4 \u05dc\u05de\u05d4\u05e0\u05d3\u05e1\u05d9\u05dd, \u05d0\u05d3\u05e8\u05d9\u05db\u05dc\u05d9\u05dd \u05d5\u05dc\u05d5\u05d5\u05e2\u05d3\u05d5\u05ea \u05ea\u05db\u05e0\u05d5\u05df \u05d5\u05d1\u05e0\u05d9\u05d9\u05d4. \u05d1\u05d9\u05e8\u05d5\u05e8 \u05d6\u05db\u05d5\u05d9\u05d5\u05ea \u05d1\u05e0\u05d9\u05d9\u05d4, \u05d0\u05d9\u05ea\u05d5\u05e8 \u05d5\u05e2\u05d3\u05d4 \u05dc\u05e4\u05d9 \u05d2\u05d5\u05e9 \u05d5\u05d7\u05dc\u05e7\u05d4, \u05d4\u05db\u05e0\u05ea \u05d1\u05e7\u05e9\u05d5\u05ea \u05d5\u05d1\u05d3\u05d9\u05e7\u05d4 \u05d4\u05e0\u05d3\u05e1\u05d9\u05ea \u05d5\u05e8\u05d2\u05d5\u05dc\u05d8\u05d5\u05e8\u05d9\u05ea.",
        "market": "\u05e4\u05d5\u05ea\u05d7 \u05e2\u05d1\u05d5\u05e8 \u05e2\u05d5\u05dc\u05dd \u05d4\u05ea\u05db\u05e0\u05d5\u05df \u05d5\u05d4\u05d1\u05e0\u05d9\u05d9\u05d4 \u05d1\u05d9\u05e9\u05e8\u05d0\u05dc",
        "headline": "\u05d4\u05d9\u05ea\u05e8 \u05d1\u05e0\u05d9\u05d9\u05d4 \u05de\u05ea\u05d7\u05d9\u05dc",
        "accent": "\u05d1\u05ea\u05db\u05e0\u05d5\u05df \u05e0\u05db\u05d5\u05df.",
        "intro": "\u05de\u05d4\u05e8\u05e2\u05d9\u05d5\u05df \u05d4\u05e8\u05d0\u05e9\u05d5\u05df \u05d5\u05e2\u05d3 \u05dc\u05d1\u05d3\u05d9\u05e7\u05ea \u05d4\u05d1\u05e7\u05e9\u05d4. Permit360 \u05e0\u05d5\u05e2\u05d3\u05d4 \u05dc\u05dc\u05d5\u05d5\u05ea \u05de\u05d4\u05e0\u05d3\u05e1\u05d9\u05dd \u05d5\u05d0\u05d3\u05e8\u05d9\u05db\u05dc\u05d9\u05dd \u05d1\u05d4\u05db\u05e0\u05ea \u05d1\u05e7\u05e9\u05d5\u05ea \u05dc\u05d4\u05d9\u05ea\u05e8 \u05d1\u05e0\u05d9\u05d9\u05d4 \u05d5\u05dc\u05e1\u05d9\u05d9\u05e2 \u05dc\u05d5\u05d5\u05e2\u05d3\u05d5\u05ea \u05d1\u05d1\u05d9\u05e6\u05d5\u05e2 \u05d1\u05d3\u05d9\u05e7\u05d5\u05ea \u05e2\u05e6\u05de\u05d0\u05d9\u05d5\u05ea \u05de\u05d1\u05d5\u05e1\u05e1\u05d5\u05ea \u05e8\u05d0\u05d9\u05d5\u05ea.",
        "pro": "\u05dc\u05de\u05d4\u05e0\u05d3\u05e1\u05d9\u05dd \u05d5\u05d0\u05d3\u05e8\u05d9\u05db\u05dc\u05d9\u05dd",
        "authority": "\u05dc\u05d5\u05d5\u05e2\u05d3\u05d5\u05ea \u05ea\u05db\u05e0\u05d5\u05df \u05d5\u05d1\u05e0\u05d9\u05d9\u05d4",
        "pro_desc": "\u05d4\u05db\u05d9\u05e8\u05d5 \u05d0\u05ea \u05d6\u05db\u05d5\u05d9\u05d5\u05ea \u05d4\u05d1\u05e0\u05d9\u05d9\u05d4 \u05d5\u05d4\u05de\u05d2\u05d1\u05dc\u05d5\u05ea \u05dc\u05e4\u05e0\u05d9 \u05ea\u05d7\u05d9\u05dc\u05ea \u05d4\u05ea\u05db\u05e0\u05d5\u05df. \u05d4\u05db\u05d9\u05e0\u05d5 \u05d0\u05ea \u05d4\u05d1\u05e7\u05e9\u05d4 \u05d1\u05dc\u05d9\u05d5\u05d5\u05d9 \u05e2\u05d5\u05d6\u05e8 \u05d4\u05e0\u05d3\u05e1\u05d9 \u05d7\u05db\u05dd.",
        "authority_desc": "\u05d1\u05d3\u05e7\u05d5 \u05d1\u05e7\u05e9\u05d5\u05ea \u05d1\u05d0\u05d5\u05e4\u05df \u05e2\u05e6\u05de\u05d0\u05d9, \u05d0\u05de\u05ea\u05d5 \u05d7\u05d9\u05e9\u05d5\u05d1\u05d9\u05dd \u05d5\u05e0\u05ea\u05d7\u05d5 \u05de\u05de\u05e6\u05d0\u05d9\u05dd \u05de\u05d5\u05dc \u05d0\u05e1\u05de\u05db\u05ea\u05d0\u05d5\u05ea \u05e8\u05d2\u05d5\u05dc\u05d8\u05d5\u05e8\u05d9\u05d5\u05ea.",
        "pro_features": ["\u05d1\u05d9\u05e8\u05d5\u05e8 \u05d6\u05db\u05d5\u05d9\u05d5\u05ea \u05d1\u05e0\u05d9\u05d9\u05d4", "\u05dc\u05d9\u05d5\u05d5\u05d9 \u05d1\u05ea\u05db\u05e0\u05d5\u05df", "\u05d4\u05db\u05e0\u05ea \u05de\u05e1\u05de\u05db\u05d9\u05dd", "\u05d1\u05d3\u05d9\u05e7\u05d4 \u05dc\u05e4\u05e0\u05d9 \u05d4\u05d2\u05e9\u05d4"],
        "authority_features": ["\u05e0\u05d9\u05ea\u05d5\u05d7 \u05e9\u05e8\u05d8\u05d5\u05d8\u05d9\u05dd", "\u05d0\u05d9\u05de\u05d5\u05ea \u05d7\u05d9\u05e9\u05d5\u05d1\u05d9\u05dd", "\u05d1\u05d3\u05d9\u05e7\u05ea \u05ea\u05e7\u05e0\u05d5\u05ea", "\u05d3\u05d5\u05d7\u05d5\u05ea \u05dc\u05d9\u05e7\u05d5\u05d9\u05d9\u05dd"],
        "advantage": "\u05dc\u05d0 \u05de\u05d7\u05db\u05d9\u05dd \u05dc\u05d5\u05d5\u05e2\u05d3\u05d4 \u05db\u05d3\u05d9 \u05dc\u05d2\u05dc\u05d5\u05ea \u05d8\u05e2\u05d5\u05d9\u05d5\u05ea.",
        "lifecycle": "\u05db\u05dc \u05ea\u05d4\u05dc\u05d9\u05da \u05d4\u05e8\u05d9\u05e9\u05d5\u05d9. \u05e4\u05dc\u05d8\u05e4\u05d5\u05e8\u05de\u05d4 \u05d0\u05d7\u05ea.",
        "steps": ["\u05d6\u05d9\u05d4\u05d5\u05d9 \u05d4\u05de\u05d2\u05e8\u05e9 \u05d5\u05d4\u05d5\u05d5\u05e2\u05d3\u05d4", "\u05d1\u05d9\u05e8\u05d5\u05e8 \u05d6\u05db\u05d5\u05d9\u05d5\u05ea \u05d5\u05de\u05d2\u05d1\u05dc\u05d5\u05ea", "\u05dc\u05d9\u05d5\u05d5\u05d9 \u05d1\u05ea\u05db\u05e0\u05d5\u05df", "\u05d1\u05e0\u05d9\u05d9\u05ea \u05d4\u05d1\u05e7\u05e9\u05d4", "\u05d1\u05d3\u05d9\u05e7\u05d4 \u05d5\u05d1\u05e7\u05e8\u05d4", "\u05de\u05e2\u05e7\u05d1 \u05d0\u05d7\u05e8 \u05ea\u05d9\u05e7\u05d5\u05e0\u05d9\u05dd"],
        "demo": "\u05d4\u05db\u05d9\u05e8\u05d5 \u05d0\u05ea \u05e1\u05d1\u05d9\u05d1\u05ea \u05d4\u05e2\u05d1\u05d5\u05d3\u05d4",
        "demo_note": "\u05d4\u05d3\u05de\u05d9\u05d4 \u05e9\u05dc \u05ea\u05d4\u05dc\u05d9\u05da \u05d4\u05e2\u05d1\u05d5\u05d3\u05d4 \u05d4\u05de\u05ea\u05d5\u05db\u05e0\u05df \u2014 \u05dc\u05d0 \u05d1\u05d3\u05d9\u05e7\u05ea \u05ea\u05d9\u05e7 \u05d0\u05de\u05d9\u05ea\u05d9.",
        "demo_pro": ["\u05d1\u05d7\u05d9\u05e8\u05ea \u05d5\u05e2\u05d3\u05d4 \u05d0\u05d5 \u05d0\u05d9\u05ea\u05d5\u05e8 \u05dc\u05e4\u05d9 \u05d2\u05d5\u05e9 \u05d5\u05d7\u05dc\u05e7\u05d4", "\u05d0\u05d9\u05ea\u05d5\u05e8 \u05d3\u05e8\u05d9\u05e9\u05d5\u05ea \u05d5\u05d6\u05db\u05d5\u05d9\u05d5\u05ea \u05d1\u05e0\u05d9\u05d9\u05d4", "\u05d1\u05e0\u05d9\u05d9\u05ea \u05d4\u05d1\u05e7\u05e9\u05d4 \u05d5\u05d1\u05d3\u05d9\u05e7\u05ea \u05de\u05d5\u05db\u05e0\u05d5\u05ea"],
        "demo_authority": ["\u05e7\u05dc\u05d9\u05d8\u05ea \u05d4\u05d1\u05e7\u05e9\u05d4", "\u05d1\u05d3\u05d9\u05e7\u05d4 \u05d4\u05e0\u05d3\u05e1\u05d9\u05ea \u05e2\u05e6\u05de\u05d0\u05d9\u05ea", "\u05d4\u05e4\u05e7\u05ea \u05de\u05de\u05e6\u05d0\u05d9\u05dd \u05d5\u05de\u05e2\u05e7\u05d1 \u05d0\u05d7\u05e8 \u05ea\u05d9\u05e7\u05d5\u05e0\u05d9\u05dd"],
        "next": "\u05d4\u05e9\u05dc\u05d1 \u05d4\u05d1\u05d0",
        "tech_title": "\u05d1\u05d9\u05e0\u05d4 \u05de\u05dc\u05d0\u05db\u05d5\u05ea\u05d9\u05ea. \u05e2\u05dd \u05d1\u05e1\u05d9\u05e1 \u05d4\u05e0\u05d3\u05e1\u05d9.",
        "tech": [
            ["\u05d9\u05d3\u05e2 \u05e8\u05d2\u05d5\u05dc\u05d8\u05d5\u05e8\u05d9 \u05d9\u05e9\u05e8\u05d0\u05dc\u05d9", "\u05ea\u05d1\u05f4\u05e2\u05d5\u05ea, \u05ea\u05e7\u05e0\u05d5\u05ea \u05d5\u05d4\u05e0\u05d7\u05d9\u05d5\u05ea \u05de\u05e8\u05d7\u05d1\u05d9\u05d5\u05ea \u05d1\u05d4\u05ea\u05d0\u05dd \u05dc\u05d5\u05d5\u05e2\u05d3\u05d4 \u05d5\u05dc\u05de\u05d2\u05e8\u05e9."],
            ["CAD & GIS", "\u05e0\u05d9\u05ea\u05d5\u05d7 \u05e9\u05e8\u05d8\u05d5\u05d8\u05d9\u05dd, \u05de\u05d9\u05d3\u05e2 \u05d2\u05d9\u05d0\u05d5\u05d2\u05e8\u05e4\u05d9 \u05d5\u05de\u05d2\u05d1\u05dc\u05d5\u05ea \u05de\u05e8\u05d7\u05d1\u05d9\u05d5\u05ea."],
            ["\u05d7\u05d9\u05e9\u05d5\u05d1\u05d9\u05dd \u05d4\u05e0\u05d3\u05e1\u05d9\u05d9\u05dd", "\u05d7\u05d9\u05e9\u05d5\u05d1\u05d9 \u05e9\u05d8\u05d7\u05d9\u05dd, \u05de\u05d9\u05d3\u05d5\u05ea \u05d5\u05d6\u05db\u05d5\u05d9\u05d5\u05ea \u05d1\u05e0\u05d9\u05d9\u05d4 \u05d4\u05e0\u05d9\u05ea\u05e0\u05d9\u05dd \u05dc\u05d0\u05d9\u05de\u05d5\u05ea."],
            ["AI \u05de\u05e7\u05d5\u05de\u05d9", "\u05d0\u05e8\u05db\u05d9\u05d8\u05e7\u05d8\u05d5\u05e8\u05d4 \u05d4\u05ea\u05d5\u05de\u05db\u05ea \u05d1\u05e2\u05d9\u05d1\u05d5\u05d3 \u05de\u05e7\u05d5\u05de\u05d9 \u05d5\u05d1\u05d4\u05d2\u05e0\u05d4 \u05e2\u05dc \u05de\u05d9\u05d3\u05e2 \u05de\u05e7\u05e6\u05d5\u05e2\u05d9."]
        ],
        "faq_title": "\u05e9\u05d0\u05dc\u05d5\u05ea \u05e0\u05e4\u05d5\u05e6\u05d5\u05ea",
        "faq": [
            ["\u05d4\u05d0\u05dd Permit360 \u05de\u05d9\u05d5\u05e2\u05d3\u05ea \u05e8\u05e7 \u05dc\u05d1\u05d3\u05d9\u05e7\u05d4?", "\u05dc\u05d0. \u05d4\u05de\u05d5\u05e6\u05e8 \u05de\u05d9\u05d5\u05e2\u05d3 \u05d2\u05dd \u05dc\u05dc\u05d9\u05d5\u05d5\u05d9 \u05d1\u05ea\u05db\u05e0\u05d5\u05df \u05d5\u05d1\u05d4\u05db\u05e0\u05ea \u05d1\u05e7\u05e9\u05d5\u05ea \u05dc\u05d4\u05d9\u05ea\u05e8 \u05d1\u05e0\u05d9\u05d9\u05d4."],
            ["\u05d0\u05d9\u05da \u05de\u05d0\u05ea\u05e8\u05d9\u05dd \u05d5\u05e2\u05d3\u05d4 \u05dc\u05e4\u05d9 \u05d2\u05d5\u05e9 \u05d5\u05d7\u05dc\u05e7\u05d4?", "\u05de\u05e1\u05dc\u05d5\u05dc \u05d4\u05e2\u05d1\u05d5\u05d3\u05d4 \u05d4\u05de\u05ea\u05d5\u05db\u05e0\u05df \u05de\u05d1\u05d5\u05e1\u05e1 \u05e2\u05dc \u05de\u05d9\u05d3\u05e2 \u05e7\u05d3\u05e1\u05d8\u05e8\u05d9 \u05e8\u05e9\u05de\u05d9 \u05d5\u05d2\u05d1\u05d5\u05dc\u05d5\u05ea \u05de\u05e8\u05d7\u05d1\u05d9 \u05ea\u05db\u05e0\u05d5\u05df."],
            ["\u05d4\u05d0\u05dd \u05d4\u05de\u05e2\u05e8\u05db\u05ea \u05de\u05e2\u05e0\u05d9\u05e7\u05d4 \u05d4\u05d9\u05ea\u05e8 \u05d1\u05e0\u05d9\u05d9\u05d4?", "\u05dc\u05d0. \u05e1\u05de\u05db\u05d5\u05ea \u05d4\u05d0\u05d9\u05e9\u05d5\u05e8 \u05e0\u05e9\u05d0\u05e8\u05ea \u05d1\u05d9\u05d3\u05d9 \u05d4\u05d2\u05d5\u05e8\u05de\u05d9\u05dd \u05d4\u05de\u05d5\u05e1\u05de\u05db\u05d9\u05dd."],
            ["\u05d4\u05d0\u05dd \u05e0\u05d9\u05ea\u05df \u05dc\u05e2\u05d1\u05d5\u05d3 \u05e2\u05dd \u05ea\u05e7\u05e0\u05d5\u05ea \u05e9\u05dc \u05d5\u05e2\u05d3\u05d5\u05ea \u05e9\u05d5\u05e0\u05d5\u05ea?", "\u05d4\u05d0\u05e8\u05db\u05d9\u05d8\u05e7\u05d8\u05d5\u05e8\u05d4 \u05de\u05d9\u05d5\u05e2\u05d3\u05ea \u05dc\u05ea\u05de\u05d9\u05db\u05d4 \u05d1\u05e8\u05d9\u05d1\u05d5\u05d9 \u05d5\u05e2\u05d3\u05d5\u05ea \u05d5\u05d1\u05d1\u05e1\u05d9\u05e1\u05d9 \u05d9\u05d3\u05e2 \u05d9\u05d9\u05e2\u05d5\u05d3\u05d9\u05d9\u05dd."],
            ["\u05d4\u05d0\u05dd \u05d4\u05de\u05e2\u05e8\u05db\u05ea \u05de\u05d7\u05dc\u05d9\u05e4\u05d4 \u05d0\u05ea \u05d4\u05de\u05d4\u05e0\u05d3\u05e1?", "\u05dc\u05d0. \u05d4\u05d9\u05d0 \u05e0\u05d5\u05e2\u05d3\u05d4 \u05dc\u05e1\u05d9\u05d9\u05e2 \u05dc\u05d1\u05e2\u05dc\u05d9 \u05d4\u05de\u05e7\u05e6\u05d5\u05e2, \u05ea\u05d5\u05da \u05e9\u05de\u05d9\u05e8\u05d4 \u05e2\u05dc \u05d0\u05d7\u05e8\u05d9\u05d5\u05ea\u05dd \u05d4\u05de\u05e7\u05e6\u05d5\u05e2\u05d9\u05ea."]
        ],
        "contact": "\u05dc\u05de\u05d9\u05d3\u05e2 \u05e0\u05d5\u05e1\u05e3 \u05d5\u05dc\u05d9\u05e6\u05d9\u05e8\u05ea \u05e7\u05e9\u05e8",
        "status": "\u05d4\u05de\u05d5\u05e6\u05e8 \u05e0\u05de\u05e6\u05d0 \u05d1\u05e4\u05d9\u05ea\u05d5\u05d7. \u05d4\u05d0\u05ea\u05e8 \u05de\u05ea\u05d0\u05e8 \u05d2\u05dd \u05d9\u05db\u05d5\u05dc\u05d5\u05ea \u05de\u05ea\u05d5\u05db\u05e0\u05e0\u05d5\u05ea."
    },
    "ar": {
        "dir": "rtl",
        "locale": "ar_IL",
        "title": "Permit360 | \u0625\u0639\u062f\u0627\u062f \u0648\u0641\u062d\u0635 \u0637\u0644\u0628\u0627\u062a \u062a\u0631\u0627\u062e\u064a\u0635 \u0627\u0644\u0628\u0646\u0627\u0621 \u0641\u064a \u0625\u0633\u0631\u0627\u0626\u064a\u0644",
        "description": "\u0645\u0646\u0635\u0629 \u0644\u0644\u0645\u0647\u0646\u062f\u0633\u064a\u0646 \u0648\u0627\u0644\u0645\u0639\u0645\u0627\u0631\u064a\u064a\u0646 \u0648\u0644\u062c\u0627\u0646 \u0627\u0644\u062a\u062e\u0637\u064a\u0637 \u0648\u0627\u0644\u0628\u0646\u0627\u0621\u060c \u0644\u0641\u062d\u0635 \u062d\u0642\u0648\u0642 \u0627\u0644\u0628\u0646\u0627\u0621 \u0648\u0625\u0639\u062f\u0627\u062f \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0648\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0645\u062e\u0637\u0637\u0627\u062a.",
        "market": "\u0635\u064f\u0645\u0645\u062a \u0644\u0642\u0637\u0627\u0639 \u0627\u0644\u062a\u062e\u0637\u064a\u0637 \u0648\u0627\u0644\u0628\u0646\u0627\u0621 \u0641\u064a \u0625\u0633\u0631\u0627\u0626\u064a\u0644",
        "headline": "\u062a\u0631\u062e\u064a\u0635 \u0627\u0644\u0628\u0646\u0627\u0621 \u064a\u0628\u062f\u0623",
        "accent": "\u0628\u062a\u062e\u0637\u064a\u0637 \u0635\u062d\u064a\u062d.",
        "intro": "\u0645\u0646 \u0627\u0644\u0641\u0643\u0631\u0629 \u0627\u0644\u0623\u0648\u0644\u0649 \u0625\u0644\u0649 \u0645\u0631\u0627\u062c\u0639\u0629 \u0627\u0644\u0637\u0644\u0628. \u062a\u0633\u0627\u0639\u062f Permit360 \u0627\u0644\u0645\u0647\u0646\u062f\u0633\u064a\u0646 \u0648\u0627\u0644\u0645\u0639\u0645\u0627\u0631\u064a\u064a\u0646 \u0641\u064a \u0625\u0639\u062f\u0627\u062f \u0637\u0644\u0628\u0627\u062a \u062a\u0631\u0627\u062e\u064a\u0635 \u0627\u0644\u0628\u0646\u0627\u0621\u060c \u0648\u062a\u062f\u0639\u0645 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0627\u0644\u0645\u0633\u062a\u0642\u0644\u0629 \u0644\u062f\u0649 \u0627\u0644\u0644\u062c\u0627\u0646 \u0627\u0644\u0645\u062e\u062a\u0635\u0629.",
        "pro": "\u0644\u0644\u0645\u0647\u0646\u062f\u0633\u064a\u0646 \u0648\u0627\u0644\u0645\u0639\u0645\u0627\u0631\u064a\u064a\u0646",
        "authority": "\u0644\u0644\u062c\u0627\u0646 \u0627\u0644\u062a\u062e\u0637\u064a\u0637 \u0648\u0627\u0644\u0628\u0646\u0627\u0621",
        "pro_desc": "\u062a\u0639\u0631\u0651\u0641 \u0639\u0644\u0649 \u062d\u0642\u0648\u0642 \u0627\u0644\u0628\u0646\u0627\u0621 \u0648\u0627\u0644\u0642\u064a\u0648\u062f \u0642\u0628\u0644 \u0627\u0644\u062a\u0635\u0645\u064a\u0645\u060c \u0648\u0627\u0633\u062a\u0639\u0646 \u0628\u0645\u0633\u0627\u0639\u062f \u0630\u0643\u064a \u0644\u0625\u0639\u062f\u0627\u062f \u0627\u0644\u0637\u0644\u0628.",
        "authority_desc": "\u0645\u0631\u0627\u062c\u0639\u0629 \u0647\u0646\u062f\u0633\u064a\u0629 \u0645\u0633\u062a\u0642\u0644\u0629 \u0648\u0627\u0644\u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u0644\u062d\u0633\u0627\u0628\u0627\u062a \u0648\u0627\u0644\u0645\u0631\u0627\u062c\u0639 \u0627\u0644\u062a\u0646\u0638\u064a\u0645\u064a\u0629.",
        "pro_features": ["\u062d\u0642\u0648\u0642 \u0627\u0644\u0628\u0646\u0627\u0621", "\u0627\u0644\u0645\u0633\u0627\u0639\u062f\u0629 \u0641\u064a \u0627\u0644\u062a\u062e\u0637\u064a\u0637", "\u0625\u0639\u062f\u0627\u062f \u0627\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a", "\u0627\u0644\u0641\u062d\u0635 \u0642\u0628\u0644 \u0627\u0644\u062a\u0642\u062f\u064a\u0645"],
        "authority_features": ["\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0645\u062e\u0637\u0637\u0627\u062a", "\u0627\u0644\u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u0644\u062d\u0633\u0627\u0628\u0627\u062a", "\u0641\u062d\u0635 \u0627\u0644\u0623\u0646\u0638\u0645\u0629", "\u062a\u0642\u0627\u0631\u064a\u0631 \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a"],
        "advantage": "\u0627\u0643\u062a\u0634\u0641 \u0627\u0644\u0645\u0634\u0643\u0644\u0627\u062a \u0642\u0628\u0644 \u062a\u0642\u062f\u064a\u0645 \u0627\u0644\u0637\u0644\u0628.",
        "lifecycle": "\u0645\u0633\u0627\u0631 \u0627\u0644\u062a\u0631\u062e\u064a\u0635 \u0627\u0644\u0643\u0627\u0645\u0644. \u0645\u0646\u0635\u0629 \u0648\u0627\u062d\u062f\u0629.",
        "steps": ["\u062a\u062d\u062f\u064a\u062f \u0627\u0644\u0623\u0631\u0636 \u0648\u0627\u0644\u0644\u062c\u0646\u0629", "\u0627\u0644\u062d\u0642\u0648\u0642 \u0648\u0627\u0644\u0642\u064a\u0648\u062f", "\u0627\u0644\u062a\u062e\u0637\u064a\u0637", "\u0625\u0639\u062f\u0627\u062f \u0627\u0644\u0637\u0644\u0628", "\u0627\u0644\u0641\u062d\u0635 \u0648\u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629", "\u0645\u062a\u0627\u0628\u0639\u0629 \u0627\u0644\u062a\u0635\u062d\u064a\u062d\u0627\u062a"],
        "demo": "\u062a\u0639\u0631\u0651\u0641 \u0639\u0644\u0649 \u0628\u064a\u0626\u0629 \u0627\u0644\u0639\u0645\u0644",
        "demo_note": "\u0639\u0631\u0636 \u062a\u0648\u0636\u064a\u062d\u064a \u0644\u0644\u0639\u0645\u0644\u064a\u0629 \u0627\u0644\u0645\u062e\u0637\u0637\u0629\u060c \u0648\u0644\u064a\u0633 \u0641\u062d\u0635\u0627\u064b \u0644\u0637\u0644\u0628 \u062d\u0642\u064a\u0642\u064a.",
        "demo_pro": ["\u0627\u062e\u062a\u064a\u0627\u0631 \u0627\u0644\u0644\u062c\u0646\u0629 \u0623\u0648 \u0627\u0644\u0628\u062d\u062b \u062d\u0633\u0628 \u0627\u0644\u062d\u0648\u0636 \u0648\u0627\u0644\u0642\u0633\u064a\u0645\u0629", "\u062a\u062d\u062f\u064a\u062f \u062d\u0642\u0648\u0642 \u0627\u0644\u0628\u0646\u0627\u0621 \u0648\u0627\u0644\u0642\u064a\u0648\u062f", "\u0625\u0639\u062f\u0627\u062f \u0627\u0644\u0637\u0644\u0628 \u0648\u0641\u062d\u0635 \u0627\u0644\u062c\u0627\u0647\u0632\u064a\u0629"],
        "demo_authority": ["\u0627\u0633\u062a\u0644\u0627\u0645 \u0627\u0644\u0637\u0644\u0628", "\u0645\u0631\u0627\u062c\u0639\u0629 \u0647\u0646\u062f\u0633\u064a\u0629 \u0645\u0633\u062a\u0642\u0644\u0629", "\u0627\u0644\u062a\u0642\u0627\u0631\u064a\u0631 \u0648\u0645\u062a\u0627\u0628\u0639\u0629 \u0627\u0644\u062a\u0635\u062d\u064a\u062d\u0627\u062a"],
        "next": "\u0627\u0644\u0645\u0631\u062d\u0644\u0629 \u0627\u0644\u062a\u0627\u0644\u064a\u0629",
        "tech_title": "\u0630\u0643\u0627\u0621 \u0627\u0635\u0637\u0646\u0627\u0639\u064a \u0628\u0623\u0633\u0627\u0633 \u0647\u0646\u062f\u0633\u064a.",
        "tech": [
            ["\u0627\u0644\u0623\u0646\u0638\u0645\u0629 \u0627\u0644\u0625\u0633\u0631\u0627\u0626\u064a\u0644\u064a\u0629", "\u0627\u0644\u0645\u062e\u0637\u0637\u0627\u062a \u0648\u0627\u0644\u0623\u0646\u0638\u0645\u0629 \u0648\u0627\u0644\u062a\u0639\u0644\u064a\u0645\u0627\u062a \u0627\u0644\u0645\u062d\u0644\u064a\u0629."],
            ["CAD & GIS", "\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0645\u062e\u0637\u0637\u0627\u062a \u0648\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062c\u063a\u0631\u0627\u0641\u064a\u0629."],
            ["\u0627\u0644\u062d\u0633\u0627\u0628\u0627\u062a \u0627\u0644\u0647\u0646\u062f\u0633\u064a\u0629", "\u062d\u0633\u0627\u0628 \u0627\u0644\u0645\u0633\u0627\u062d\u0627\u062a \u0648\u0627\u0644\u0623\u0628\u0639\u0627\u062f \u0648\u062d\u0642\u0648\u0642 \u0627\u0644\u0628\u0646\u0627\u0621."],
            ["\u0627\u0644\u0630\u0643\u0627\u0621 \u0627\u0644\u0627\u0635\u0637\u0646\u0627\u0639\u064a \u0627\u0644\u0645\u062d\u0644\u064a", "\u0628\u0646\u064a\u0629 \u062a\u062f\u0639\u0645 \u0627\u0644\u0645\u0639\u0627\u0644\u062c\u0629 \u0627\u0644\u0645\u062d\u0644\u064a\u0629 \u0648\u062d\u0645\u0627\u064a\u0629 \u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0627\u062a."]
        ],
        "faq_title": "\u0623\u0633\u0626\u0644\u0629 \u0634\u0627\u0626\u0639\u0629",
        "faq": [
            ["\u0647\u0644 \u0627\u0644\u0645\u0646\u0635\u0629 \u0644\u0644\u0641\u062d\u0635 \u0641\u0642\u0637\u061f", "\u0644\u0627\u060c \u0641\u0647\u064a \u0645\u0635\u0645\u0645\u0629 \u0623\u064a\u0636\u0627\u064b \u0644\u0644\u0645\u0633\u0627\u0639\u062f\u0629 \u0641\u064a \u0627\u0644\u062a\u062e\u0637\u064a\u0637 \u0648\u0625\u0639\u062f\u0627\u062f \u0637\u0644\u0628\u0627\u062a \u062a\u0631\u0627\u062e\u064a\u0635 \u0627\u0644\u0628\u0646\u0627\u0621."],
            ["\u0647\u0644 \u064a\u0645\u0643\u0646 \u062a\u062d\u062f\u064a\u062f \u0627\u0644\u0644\u062c\u0646\u0629 \u062d\u0633\u0628 \u0627\u0644\u062d\u0648\u0636 \u0648\u0627\u0644\u0642\u0633\u064a\u0645\u0629\u061f", "\u0647\u0630\u0627 \u0645\u0633\u0627\u0631 \u0645\u062e\u0637\u0637 \u064a\u0639\u062a\u0645\u062f \u0639\u0644\u0649 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0645\u0633\u0627\u062d\u064a\u0629 \u0627\u0644\u0631\u0633\u0645\u064a\u0629."],
            ["\u0647\u0644 \u062a\u0645\u0646\u062d \u0627\u0644\u0645\u0646\u0635\u0629 \u0631\u062e\u0635\u0629 \u0627\u0644\u0628\u0646\u0627\u0621\u061f", "\u0644\u0627\u060c \u062a\u0628\u0642\u0649 \u0635\u0644\u0627\u062d\u064a\u0629 \u0627\u0644\u0645\u0648\u0627\u0641\u0642\u0629 \u0644\u062f\u0649 \u0627\u0644\u062c\u0647\u0627\u062a \u0627\u0644\u0645\u062e\u062a\u0635\u0629."],
            ["\u0647\u0644 \u062a\u062f\u0639\u0645 \u0644\u062c\u0627\u0646\u0627\u064b \u0645\u062e\u062a\u0644\u0641\u0629\u061f", "\u0635\u064f\u0645\u0645\u062a \u0627\u0644\u0628\u0646\u064a\u0629 \u0644\u062f\u0639\u0645 \u0644\u062c\u0627\u0646 \u0645\u062a\u0639\u062f\u062f\u0629 \u0648\u0642\u0648\u0627\u0639\u062f \u0645\u0639\u0631\u0641\u0629 \u0645\u062e\u0635\u0635\u0629."],
            ["\u0647\u0644 \u062a\u0633\u062a\u0628\u062f\u0644 \u0627\u0644\u0645\u0647\u0646\u062f\u0633\u061f", "\u0644\u0627\u060c \u062a\u0628\u0642\u0649 \u0627\u0644\u0645\u0633\u0624\u0648\u0644\u064a\u0629 \u0627\u0644\u0645\u0647\u0646\u064a\u0629 \u0644\u062f\u0649 \u0627\u0644\u0645\u062e\u062a\u0635\u064a\u0646."]
        ],
        "contact": "\u0644\u0644\u0645\u0632\u064a\u062f \u0645\u0646 \u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0648\u0627\u0644\u062a\u0648\u0627\u0635\u0644",
        "status": "\u0627\u0644\u0645\u0646\u062a\u062c \u0642\u064a\u062f \u0627\u0644\u062a\u0637\u0648\u064a\u0631. \u064a\u062a\u0636\u0645\u0646 \u0627\u0644\u0645\u0648\u0642\u0639 \u0642\u062f\u0631\u0627\u062a \u0645\u062e\u0637\u0637\u0627\u064b \u0644\u0647\u0627."
    },
    "en": {
        "dir": "ltr",
        "locale": "en_IL",
        "title": "Permit360 | Building Permit Preparation and Review in Israel",
        "description": "AI-powered building permit preparation and independent regulatory review for engineers, architects and Israeli planning committees.",
        "market": "Built for Israel's planning and building sector",
        "headline": "Better permits begin",
        "accent": "with better planning.",
        "intro": "From initial planning to independent review. Permit360 is designed to help engineers prepare building permit applications and planning committees validate engineering and regulatory evidence.",
        "pro": "Engineers & architects",
        "authority": "Planning committees",
        "pro_desc": "Understand building rights and restrictions before designing. Prepare applications with an intelligent engineering assistant.",
        "authority_desc": "Perform independent engineering and regulatory reviews with traceable measurements and evidence.",
        "pro_features": ["Building rights", "Planning assistance", "Document preparation", "Pre-submission validation"],
        "authority_features": ["Drawing analysis", "Calculation verification", "Regulatory checks", "Defect reports"],
        "advantage": "Find problems before submission.",
        "lifecycle": "The entire permit lifecycle. One platform.",
        "steps": ["Identify property and committee", "Discover rights and constraints", "Planning assistance", "Build application", "Review and validate", "Track corrections"],
        "demo": "Explore the workspace",
        "demo_note": "Illustration of the intended product workflow, not a real permit review.",
        "demo_pro": ["Select committee or search by block and parcel", "Discover building rights and restrictions", "Prepare the application"],
        "demo_authority": ["Receive application", "Perform independent engineering review", "Report findings and track corrections"],
        "next": "Next stage",
        "tech_title": "Artificial intelligence. Engineering foundations.",
        "tech": [
            ["Israeli regulatory intelligence", "Planning regulations, statutory plans and spatial guidelines."],
            ["CAD & GIS", "Architectural drawings and geographic intelligence."],
            ["Engineering calculations", "Traceable areas, measurements and building rights."],
            ["Local AI", "Architecture supporting local processing and information protection."]
        ],
        "faq_title": "Frequently asked questions",
        "faq": [
            ["Is Permit360 only a review system?", "No. It is designed to assist with planning and application preparation as well."],
            ["Can I identify a committee by block and parcel?", "This is a planned workflow using official cadastral and planning jurisdiction data."],
            ["Does Permit360 issue permits?", "No. Statutory approval remains with authorized authorities."],
            ["Does it support multiple committees?", "The architecture supports multiple committees and dedicated regulatory knowledge bases."],
            ["Does it replace engineers?", "No. Professional responsibility remains with qualified professionals."]
        ],
        "contact": "Learn more and contact us",
        "status": "Product in development. This website also describes planned capabilities."
    },
    "ru": {
        "dir": "ltr",
        "locale": "ru_IL",
        "title": "Permit360 | \u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u0439 \u043d\u0430 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u0441\u0442\u0432\u043e \u0432 \u0418\u0437\u0440\u0430\u0438\u043b\u0435",
        "description": "\u041f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0430 \u0418\u0418 \u0434\u043b\u044f \u0438\u043d\u0436\u0435\u043d\u0435\u0440\u043e\u0432, \u0430\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u043e\u0440\u043e\u0432 \u0438 \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u0439 \u043f\u043e \u043f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044e: \u043f\u0440\u0430\u0432\u0430 \u0437\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438, \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u0439 \u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0447\u0435\u0440\u0442\u0435\u0436\u0435\u0439.",
        "market": "\u0414\u043b\u044f \u0441\u0444\u0435\u0440\u044b \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u0441\u0442\u0432\u0430 \u0438 \u043f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f \u0432 \u0418\u0437\u0440\u0430\u0438\u043b\u0435",
        "headline": "\u0420\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u043d\u0430 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u0441\u0442\u0432\u043e",
        "accent": "\u043d\u0430\u0447\u0438\u043d\u0430\u0435\u0442\u0441\u044f \u0441 \u0442\u043e\u0447\u043d\u043e\u0433\u043e \u043f\u0440\u043e\u0435\u043a\u0442\u0430.",
        "intro": "\u041e\u0442 \u043f\u0435\u0440\u0432\u043e\u043d\u0430\u0447\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u043f\u0440\u043e\u0435\u043a\u0442\u0430 \u0434\u043e \u043d\u0435\u0437\u0430\u0432\u0438\u0441\u0438\u043c\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438. Permit360 \u043f\u0440\u0435\u0434\u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0430 \u0434\u043b\u044f \u043f\u043e\u043c\u043e\u0449\u0438 \u0438\u043d\u0436\u0435\u043d\u0435\u0440\u0430\u043c \u0432 \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0435 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u0439 \u0438 \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u044f\u043c \u0432 \u0438\u0445 \u043d\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0435.",
        "pro": "\u0418\u043d\u0436\u0435\u043d\u0435\u0440\u0430\u043c \u0438 \u0430\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u043e\u0440\u0430\u043c",
        "authority": "\u041a\u043e\u043c\u0438\u0441\u0441\u0438\u044f\u043c \u043f\u043e \u043f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044e",
        "pro_desc": "\u041e\u043f\u0440\u0435\u0434\u0435\u043b\u044f\u0439\u0442\u0435 \u043f\u0440\u0430\u0432\u0430 \u0437\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0438 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f \u0434\u043e \u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f. \u0413\u043e\u0442\u043e\u0432\u044c\u0442\u0435 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b \u0441 \u0438\u043d\u0442\u0435\u043b\u043b\u0435\u043a\u0442\u0443\u0430\u043b\u044c\u043d\u044b\u043c \u043f\u043e\u043c\u043e\u0449\u043d\u0438\u043a\u043e\u043c.",
        "authority_desc": "\u041f\u0440\u043e\u0432\u043e\u0434\u0438\u0442\u0435 \u043d\u0435\u0437\u0430\u0432\u0438\u0441\u0438\u043c\u0443\u044e \u0438\u043d\u0436\u0435\u043d\u0435\u0440\u043d\u0443\u044e \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443 \u0441 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435\u043c \u043d\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0445 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u043e\u0432.",
        "pro_features": ["\u041f\u0440\u0430\u0432\u0430 \u0437\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438", "\u041f\u043e\u043c\u043e\u0449\u044c \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0438", "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u043e\u0432", "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0434\u043e \u043f\u043e\u0434\u0430\u0447\u0438"],
        "authority_features": ["\u0410\u043d\u0430\u043b\u0438\u0437 \u0447\u0435\u0440\u0442\u0435\u0436\u0435\u0439", "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0440\u0430\u0441\u0447\u0451\u0442\u043e\u0432", "\u041d\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430", "\u041e\u0442\u0447\u0451\u0442\u044b \u043e \u0437\u0430\u043c\u0435\u0447\u0430\u043d\u0438\u044f\u0445"],
        "advantage": "\u0412\u044b\u044f\u0432\u043b\u044f\u0439\u0442\u0435 \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0434\u043e \u043f\u043e\u0434\u0430\u0447\u0438 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u044f.",
        "lifecycle": "\u0412\u0435\u0441\u044c \u043f\u0440\u043e\u0446\u0435\u0441\u0441. \u041e\u0434\u043d\u0430 \u043f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0430.",
        "steps": ["\u041e\u043f\u0440\u0435\u0434\u0435\u043b\u0435\u043d\u0438\u0435 \u0443\u0447\u0430\u0441\u0442\u043a\u0430", "\u041f\u0440\u0430\u0432\u0430 \u0438 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f", "\u041f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435", "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u044f", "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430", "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c \u0438\u0441\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0439"],
        "demo": "\u0420\u0430\u0431\u043e\u0447\u0430\u044f \u0441\u0440\u0435\u0434\u0430 Permit360",
        "demo_note": "\u0414\u0435\u043c\u043e\u043d\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u043f\u043b\u0430\u043d\u0438\u0440\u0443\u0435\u043c\u043e\u0433\u043e \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u0430, \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0440\u0435\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u044f.",
        "demo_pro": ["\u041f\u043e\u0438\u0441\u043a \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u0438 \u0438 \u043a\u0430\u0434\u0430\u0441\u0442\u0440\u043e\u0432\u043e\u0433\u043e \u0443\u0447\u0430\u0441\u0442\u043a\u0430", "\u041f\u0440\u0430\u0432\u0430 \u0437\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0438 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f", "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u044f"],
        "demo_authority": ["\u041f\u0440\u0438\u0451\u043c \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u044f", "\u041d\u0435\u0437\u0430\u0432\u0438\u0441\u0438\u043c\u0430\u044f \u0438\u043d\u0436\u0435\u043d\u0435\u0440\u043d\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430", "\u041e\u0442\u0447\u0451\u0442 \u0438 \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c \u0438\u0441\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0439"],
        "next": "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u044d\u0442\u0430\u043f",
        "tech_title": "\u0418\u0418 \u043d\u0430 \u0438\u043d\u0436\u0435\u043d\u0435\u0440\u043d\u043e\u0439 \u043e\u0441\u043d\u043e\u0432\u0435.",
        "tech": [
            ["\u041d\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u0430\u044f \u0431\u0430\u0437\u0430 \u0418\u0437\u0440\u0430\u0438\u043b\u044f", "\u0413\u0440\u0430\u0434\u043e\u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043b\u0430\u043d\u044b \u0438 \u0442\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f."],
            ["CAD & GIS", "\u0410\u043d\u0430\u043b\u0438\u0437 \u0447\u0435\u0440\u0442\u0435\u0436\u0435\u0439 \u0438 \u0433\u0435\u043e\u0433\u0440\u0430\u0444\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445."],
            ["\u0418\u043d\u0436\u0435\u043d\u0435\u0440\u043d\u044b\u0435 \u0440\u0430\u0441\u0447\u0451\u0442\u044b", "\u041f\u0440\u043e\u0432\u0435\u0440\u044f\u0435\u043c\u044b\u0435 \u043f\u043b\u043e\u0449\u0430\u0434\u0438, \u0440\u0430\u0437\u043c\u0435\u0440\u044b \u0438 \u043f\u0440\u0430\u0432\u0430 \u0437\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438."],
            ["\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0418\u0418", "\u0410\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430 \u0441 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u043e\u0439 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e\u0439 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0434\u0430\u043d\u043d\u044b\u0445."]
        ],
        "faq_title": "\u0427\u0430\u0441\u0442\u043e \u0437\u0430\u0434\u0430\u0432\u0430\u0435\u043c\u044b\u0435 \u0432\u043e\u043f\u0440\u043e\u0441\u044b",
        "faq": [
            ["\u042d\u0442\u043e \u0442\u043e\u043b\u044c\u043a\u043e \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438?", "\u041d\u0435\u0442. \u041e\u043d\u0430 \u043f\u0440\u0435\u0434\u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0430 \u0442\u0430\u043a\u0436\u0435 \u0434\u043b\u044f \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0438 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u0439 \u0438 \u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f."],
            ["\u041c\u043e\u0436\u043d\u043e \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438\u0442\u044c \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u044e \u043f\u043e \u043a\u0430\u0434\u0430\u0441\u0442\u0440\u043e\u0432\u043e\u043c\u0443 \u0443\u0447\u0430\u0441\u0442\u043a\u0443?", "\u0422\u0430\u043a\u043e\u0439 \u0441\u0446\u0435\u043d\u0430\u0440\u0438\u0439 \u043f\u0440\u0435\u0434\u0443\u0441\u043c\u043e\u0442\u0440\u0435\u043d \u0441 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435\u043c \u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0445 \u0433\u0435\u043e\u0433\u0440\u0430\u0444\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445."],
            ["\u0412\u044b\u0434\u0430\u0451\u0442 \u043b\u0438 \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u044f?", "\u041d\u0435\u0442. \u041f\u043e\u043b\u043d\u043e\u043c\u043e\u0447\u0438\u044f \u043e\u0441\u0442\u0430\u044e\u0442\u0441\u044f \u0443 \u0441\u043e\u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0443\u044e\u0449\u0438\u0445 \u043e\u0440\u0433\u0430\u043d\u043e\u0432."],
            ["\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u044e\u0442\u0441\u044f \u0440\u0430\u0437\u043d\u044b\u0435 \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u0438?", "\u0410\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430 \u043f\u0440\u0435\u0434\u0443\u0441\u043c\u0430\u0442\u0440\u0438\u0432\u0430\u0435\u0442 \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u044b\u0435 \u043d\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0435 \u0431\u0430\u0437\u044b \u0434\u043b\u044f \u0440\u0430\u0437\u043b\u0438\u0447\u043d\u044b\u0445 \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u0439."],
            ["\u0417\u0430\u043c\u0435\u043d\u044f\u0435\u0442 \u043b\u0438 \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u0438\u043d\u0436\u0435\u043d\u0435\u0440\u0430?", "\u041d\u0435\u0442. \u041e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0435\u043d\u043d\u043e\u0441\u0442\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f \u0443 \u043a\u0432\u0430\u043b\u0438\u0444\u0438\u0446\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0445 \u0441\u043f\u0435\u0446\u0438\u0430\u043b\u0438\u0441\u0442\u043e\u0432."]
        ],
        "contact": "\u0423\u0437\u043d\u0430\u0442\u044c \u0431\u043e\u043b\u044c\u0448\u0435 \u0438 \u0441\u0432\u044f\u0437\u0430\u0442\u044c\u0441\u044f \u0441 \u043d\u0430\u043c\u0438",
        "status": "\u041f\u0440\u043e\u0434\u0443\u043a\u0442 \u0432 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435. \u041d\u0430 \u0441\u0430\u0439\u0442\u0435 \u043f\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u044b \u0442\u0430\u043a\u0436\u0435 \u043f\u043b\u0430\u043d\u0438\u0440\u0443\u0435\u043c\u044b\u0435 \u0444\u0443\u043d\u043a\u0446\u0438\u0438."
    }
}

CSS = """
:root {
  --navy:#081c2b;
  --teal:#007d78;
  --mint:#66e4c7;
  --ink:#152f40;
  --muted:#607483;
  --paper:#f4f8f8;
}
*{box-sizing:border-box}
body{margin:0;font-family:Arial,system-ui,sans-serif;color:var(--ink);background:var(--paper);line-height:1.75}
h1,h2,h3,p{margin-block-start:0}
a{color:inherit;text-decoration:none}
button{font:inherit;cursor:pointer}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #1b9c9a;outline-offset:5px}
.wrap{max-width:1220px;margin:auto;padding-inline:28px}
header{background:var(--navy);color:white;border-bottom:1px solid #284452}
.nav{display:flex;justify-content:space-between;align-items:center;gap:24px;min-height:88px;flex-wrap:wrap}
.brand{direction:ltr;font-weight:800;font-size:30px;line-height:1.1;letter-spacing:-1px}
.brand span{color:var(--mint)}
.brand small{display:block;font-size:12px;color:#afc5ce;font-weight:400;letter-spacing:.5px;margin-top:5px}
.languages{display:flex;gap:5px;direction:ltr;flex-wrap:wrap}
.languages a{padding:7px 11px;border-radius:6px;font-size:14px}
.languages a[aria-current]{background:#284858;color:var(--mint)}
.hero{background:radial-gradient(ellipse at 20% 70%,#17515a,transparent 65%),var(--navy);color:white;padding:80px 0}
.hero-grid{display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:56px}
.eyebrow{color:var(--mint);font-size:13px;font-weight:bold;letter-spacing:.5px}
h1{font-size:clamp(38px,5vw,72px);line-height:1.12;letter-spacing:-1.7px;margin:20px 0}
h1 span{display:block;color:var(--mint)}
.hero p{color:#c7d9df;font-size:18px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}
.btn{display:inline-block;padding:12px 24px;border-radius:7px;font-weight:bold;background:var(--mint);color:var(--navy);border:1px solid var(--mint)}
.btn.secondary{background:transparent;color:white;border-color:#71939e}
.art{border:1px solid #41636d;border-radius:18px;background:#102d3c;padding:20px;box-shadow:0 20px 70px #0003}
.art img{width:100%;display:block}
.art small{display:block;color:#a5c4cb;text-align:center;margin-top:10px}
.strip{background:white;border-bottom:1px solid #dce6e9;padding:20px;text-align:center;color:#42626e;font-size:13px;font-weight:bold;word-spacing:8px}
.section{padding-block:75px}
h2{font-size:clamp(28px,3.5vw,46px);line-height:1.3;margin-bottom:24px;letter-spacing:-.6px}
h3{font-size:23px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.card{background:white;border:1px solid #dce6e9;padding:35px;border-radius:15px;box-shadow:0 8px 30px #123c4508}
.label{font-size:13px;color:var(--teal);font-weight:bold;direction:ltr;text-align:start}
.card p{color:var(--muted)}
.feature{display:block;padding:8px 0;border-bottom:1px solid #e7efef}
.feature::before{content:'\u2713';color:var(--teal);margin-inline-end:10px;font-weight:bold}
.advantage{background:#dff3ef;text-align:center;padding:48px 20px}
.advantage h2{margin:0}
.demo{background:#e8f1f2}
.demo-box{background:white;border-radius:14px;border:1px solid #cbdcdf;overflow:hidden}
.demo-tabs{display:flex;background:#102e3d;padding:16px;gap:8px;flex-wrap:wrap}
.demo-tabs button{flex:1;padding:12px;background:transparent;color:white;border:1px solid #557981;border-radius:7px}
.demo-tabs button[aria-pressed=true]{background:var(--mint);color:var(--navy)}
.demo-inner{display:grid;grid-template-columns:1fr 1fr;gap:25px;padding:30px;align-items:center}
.demo-inner img{width:100%;background:#102e3d;border-radius:9px}
.demo-copy{padding:20px}
.demo-copy h3{min-height:3em}
.demo-copy button{background:var(--teal);color:white;border:0;border-radius:7px;padding:12px 20px}
.flow{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.step{background:white;padding:25px;border-radius:8px;border-top:3px solid var(--teal)}
.step b{display:block;color:var(--teal);font-size:30px;font-weight:400}
.dark{background:#102e3d;color:white}
.dark .card{background:#183e4c;border-color:#365d68;box-shadow:none}
.dark .card p{color:#c0d5db}
details{background:white;padding:16px 22px;border:1px solid #dae5e8;border-radius:9px;margin:10px 0}
summary{cursor:pointer;font-weight:bold}
details p{margin:12px 0 0;color:var(--muted)}
.contact{text-align:center;background:#def3ef}
.contact .btn{background:var(--teal);color:white;border-color:var(--teal)}
footer{background:var(--navy);color:#b1c8d2;padding:30px 0;font-size:13px}
footer strong{display:block;color:white;margin-bottom:10px}
@media(max-width:850px){
.hero-grid,.two,.demo-inner{grid-template-columns:1fr}
.hero{padding:45px 0}
.section{padding-block:45px}
.flow{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:480px){
.wrap{padding-inline:18px}
.card,.demo-inner,.demo-copy{padding:18px}
.nav{padding-block:15px}
h1{letter-spacing:-.5px}
.flow{grid-template-columns:1fr 1fr}
.step{padding:15px}
}
"""

SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 390">
<defs>
 <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
  <path d="M24 0H0V24" stroke="#254655" fill="none" stroke-width=".7"/>
 </pattern>
 <linearGradient id="wall" x2="1" y2="1">
  <stop stop-color="#356b7b"/><stop offset="1" stop-color="#153a49"/>
 </linearGradient>
</defs>
<rect width="640" height="390" rx="12" fill="#0d2737"/>
<rect width="640" height="390" fill="url(#grid)"/>
<path d="M70 230 305 85 575 225 340 370Z" fill="#183f4b" stroke="#70c7ce"/>
<path d="M125 235 310 125 515 235 335 338Z" fill="#22645f" fill-opacity=".35"
 stroke="#66e4c7" stroke-width="2" stroke-dasharray="8 5"/>
<g stroke="#8acbd4" stroke-width="1.5" stroke-linejoin="round">
 <path d="M208 175 315 114 428 175 320 240Z" fill="#326778"/>
 <path d="M208 175 320 240 320 290 208 225Z" fill="url(#wall)"/>
 <path d="M320 240 428 175 428 225 320 290Z" fill="#194655"/>
 <path d="M208 125 315 64 428 125 320 190Z" fill="#326778"/>
 <path d="M208 125 320 190 320 240 208 175Z" fill="url(#wall)"/>
 <path d="M320 190 428 125 428 175 320 240Z" fill="#194655"/>
 <path d="M208 125 315 30 428 125 320 190Z" fill="#497e8a"/>
 <path d="M315 30 320 190" fill="none"/>
</g>
<g fill="#9ad6de" opacity=".8">
 <path d="M225 146l22 13v22l-22-13Z M265 169l22 13v22l-22-13Z"/>
 <path d="M225 196l22 13v22l-22-13Z M265 219l22 13v22l-22-13Z"/>
 <path d="M340 196l22-13v22l-22 13Z M382 171l22-13v22l-22 13Z"/>
 <path d="M340 246l22-13v22l-22 13Z M382 221l22-13v22l-22 13Z"/>
</g>
<g stroke="#66e4c7" fill="none" stroke-dasharray="5 4">
 <path d="M70 230 45 245 320 387"/>
 <path d="M315 30H475V226"/>
 <path d="M125 235 335 338 515 235"/>
</g>
<g font-family="Arial" font-size="12">
 <rect x="14" y="18" width="180" height="85" rx="8" fill="#163948" stroke="#48727d"/>
 <text x="29" y="42" fill="#66e4c7">PERMIT360 INTELLIGENCE</text>
 <path d="M29 55H176" stroke="#436570"/>
 <text x="29" y="76" fill="#c3dde1">Planning \u00b7 Regulations</text>
 <text x="29" y="93" fill="#c3dde1">Engineering \u00b7 GIS</text>
 <rect x="457" y="275" width="166" height="80" rx="8" fill="#163948" stroke="#48727d"/>
 <text x="473" y="299" fill="#66e4c7">PROJECT WORKSPACE</text>
 <path d="M473 310H609" stroke="#436570"/>
 <text x="473" y="332" fill="#c3dde1">Evidence-based review</text>
</g>
</svg>
"""

ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
(ASSETS / "style.css").write_text(CSS, encoding="utf-8")
(ASSETS / "architecture.svg").write_text(SVG, encoding="utf-8")

SCRIPT = """
const demo = document.querySelector('#workspace');
const data = JSON.parse(document.querySelector('#demo-data').textContent);
let role = 'pro';
let stage = 0;

function updateDemo() {
    document.querySelector('#demo-stage').textContent =
        String(stage + 1).padStart(2, '0') + ' / 03';
    document.querySelector('#demo-task').textContent =
        data[role][stage];
    document.querySelectorAll('[data-role]').forEach(button => {
        button.setAttribute(
            'aria-pressed',
            String(button.dataset.role === role)
        );
    });
}

demo.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.role) {
        role = button.dataset.role;
        stage = 0;
    } else if (button.id === 'next-stage') {
        stage = (stage + 1) % data[role].length;
    }
    updateDemo();
});
updateDemo();
"""

(ASSETS / "demo.js").write_text(SCRIPT, encoding="utf-8")

def safe_json(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")

def render(lang, d):
    canonical = f"{BASE}/{lang}/"

    alternate = "\n".join(
        f'<link rel="alternate" hreflang="{code}-IL" href="{BASE}/{code}/">'
        for code in LANGS
    )

    alternate += f'\n<link rel="alternate" hreflang="x-default" href="{BASE}/he/">'

    nav = "".join(
        f'<a href="/{code}/" lang="{code}"'
        + (' aria-current="page"' if code == lang else '')
        + f'>{name}</a>'
        for code, name in [
            ("he", "\u05e2\u05d1\u05e8\u05d9\u05ea"), ("ar", "\u0627\u0644\u0639\u0631\u0628\u064a\u0629"),
            ("en", "English"), ("ru", "\u0420\u0443\u0441\u0441\u043a\u0438\u0439")
        ]
    )

    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://kortexd.com/#organization",
                "name": "Kortex Digital",
                "url": "https://kortexd.com/"
            },
            {
                "@type": "SoftwareApplication",
                "name": "Permit360",
                "description": d["description"],
                "applicationCategory": "BusinessApplication",
                "inLanguage": list(LANGS),
                "url": canonical,
                "publisher": {
                    "@id": "https://kortexd.com/#organization"
                }
            },
            {
                "@type": "WebPage",
                "name": d["title"],
                "url": canonical,
                "description": d["description"],
                "inLanguage": lang
            }
        ]
    }

    features = lambda items: "".join(
        f'<span class="feature">{escape(item)}</span>'
        for item in items
    )

    flow = "".join(
        f'<article class="step"><b>{i:02d}</b>{escape(item)}</article>'
        for i, item in enumerate(d["steps"], 1)
    )

    tech = "".join(
        f'<article class="card"><h3>{escape(title)}</h3>'
        f'<p>{escape(desc)}</p></article>'
        for title, desc in d["tech"]
    )

    faq = "".join(
        f'<details><summary>{escape(q)}</summary>'
        f'<p>{escape(a)}</p></details>'
        for q, a in d["faq"]
    )

    demo_json = safe_json({
        "pro": d["demo_pro"],
        "authority": d["demo_authority"]
    })

    return f"""<!doctype html>
<html lang="{lang}" dir="{d['dir']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(d['title'])}</title>
<meta name="description" content="{escape(d['description'], quote=True)}">
<meta name="robots" content="index,follow">
<meta name="theme-color" content="#081c2b">
<link rel="canonical" href="{canonical}">
{alternate}
<meta property="og:type" content="website">
<meta property="og:title" content="{escape(d['title'], quote=True)}">
<meta property="og:description" content="{escape(d['description'], quote=True)}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="{d['locale']}">
<meta property="og:site_name" content="Permit360 by Kortex Digital">
<link rel="stylesheet" href="/assets/style.css">
<script type="application/ld+json">{safe_json(schema)}</script>
<script src="/assets/demo.js" defer></script>
</head>
<body>
<header>
<nav class="wrap nav">
<a class="brand" href="/{lang}/">Permit<span>360</span>
<small>by Kortex Digital</small></a>
<div class="languages">{nav}</div>
</nav>
</header>

<main>
<section class="hero">
<div class="wrap hero-grid">
<div>
<div class="eyebrow">{d['market']}</div>
<h1>{d['headline']}<span>{d['accent']}</span></h1>
<p>{d['intro']}</p>
<div class="actions">
<a class="btn" href="#pro">{d['pro']}</a>
<a class="btn secondary" href="#authority">{d['authority']}</a>
</div>
</div>
<div class="art">
<img src="/assets/architecture.svg" width="640" height="390"
alt="{escape(d['demo_note'], quote=True)}">
<small>{d['demo_note']}</small>
</div>
</div>
</section>

<div class="strip">AI \u00b7 CAD \u00b7 GIS \u00b7 GovTech \u00b7 RegTech</div>

<section class="section wrap">
<h2>{d['lifecycle']}</h2>
<div class="two">
<article class="card" id="pro">
<div class="label">PERMIT360 PRO</div>
<h3>{d['pro']}</h3>
<p>{d['pro_desc']}</p>
{features(d['pro_features'])}
</article>
<article class="card" id="authority">
<div class="label">PERMIT360 AUTHORITY</div>
<h3>{d['authority']}</h3>
<p>{d['authority_desc']}</p>
{features(d['authority_features'])}
</article>
</div>
</section>

<section class="advantage">
<h2>{d['advantage']}</h2>
</section>

<section class="section demo" id="workspace">
<div class="wrap">
<h2>{d['demo']}</h2>
<p>{d['demo_note']}</p>
<div class="demo-box">
<div class="demo-tabs">
<button data-role="pro" aria-pressed="true">{d['pro']}</button>
<button data-role="authority" aria-pressed="false">{d['authority']}</button>
</div>
<div class="demo-inner">
<img src="/assets/architecture.svg" width="640" height="390" loading="lazy"
alt="{escape(d['demo_note'], quote=True)}">
<div class="demo-copy" aria-live="polite">
<p id="demo-stage">01 / 03</p>
<h3 id="demo-task">{d['demo_pro'][0]}</h3>
<button id="next-stage">{d['next']}</button>
</div>
</div>
</div>
<script type="application/json" id="demo-data">{demo_json}</script>
</div>
</section>

<section class="section wrap">
<h2>{d['lifecycle']}</h2>
<div class="flow">{flow}</div>
</section>

<section class="section dark">
<div class="wrap">
<h2>{d['tech_title']}</h2>
<div class="two">{tech}</div>
</div>
</section>

<section class="section wrap">
<h2>{d['faq_title']}</h2>
{faq}
</section>

<section class="section contact">
<div class="wrap">
<h2>{d['accent']}</h2>
<a class="btn" href="https://kortexd.com/">{d['contact']}</a>
</div>
</section>
</main>

<footer>
<div class="wrap">
<strong dir="ltr">Permit360 by Kortex Digital</strong>
<p>{d['status']}</p>
<a href="https://kortexd.com/">kortexd.com</a>
</div>
</footer>
</body>
</html>"""

for lang, content in LANGS.items():
    folder = ROOT / lang
    folder.mkdir(exist_ok=True)
    (folder / "index.html").write_text(
        render(lang, content),
        encoding="utf-8"
    )

(ROOT / "index.html").write_text(
    """<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Permit360 by Kortex Digital</title>
<link rel="canonical" href="https://permit.kortexd.com/he/">
<meta http-equiv="refresh" content="0;url=/he/">
</head><body><a href="/he/">Permit360 \u2014 \u05e2\u05d1\u05e8\u05d9\u05ea</a></body></html>""",
    encoding="utf-8"
)

sitemap = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
    'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
]

for lang in LANGS:
    sitemap.append(f"<url><loc>{BASE}/{lang}/</loc>")
    for alt in LANGS:
        sitemap.append(
            f'<xhtml:link rel="alternate" hreflang="{alt}-IL" '
            f'href="{BASE}/{alt}/"/>'
        )
    sitemap.append(
        f'<xhtml:link rel="alternate" hreflang="x-default" '
        f'href="{BASE}/he/"/>'
    )
    sitemap.append("</url>")

sitemap.append("</urlset>")
(ROOT / "sitemap.xml").write_text("\n".join(sitemap), encoding="utf-8")

(ROOT / "robots.txt").write_text(
    f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n",
    encoding="utf-8"
)

(ROOT / "llms.txt").write_text(
    "# Permit360 by Kortex Digital\n\n"
    "> Building permit preparation and independent review "
    "for the Israeli planning and building sector.\n\n"
    "Permit360 is under development. Its intended workflows "
    "serve engineers, architects and planning committees. "
    "The platform does not issue statutory building permits.\n\n"
    + "\n".join(f"- [{lang}]({BASE}/{lang}/)" for lang in LANGS),
    encoding="utf-8"
)

README = """
# Permit360 by Kortex Digital

## Preview

Run from inside the release directory:

    python -m http.server 8080

Open http://localhost:8080/he/

Available languages: Hebrew, Arabic, English, Russian.

## Important

- Public product website only.
- No confidential application data.
- Demonstrations are illustrative.
- No authenticated application integration.
- No production DNS changes.
- Contact currently links to kortexd.com.
- llms.txt is optional and does not guarantee AI visibility.
- No search ranking or product performance is guaranteed.

## Deployment

Deploy the static website to permit.kortexd.com over HTTPS.
Prefer a server-side redirect from / to /he/.
Use the existing Kortex Digital infrastructure where possible.
Do not deploy before approval and acceptance testing.
"""

(ROOT / "README.md").write_text(README, encoding="utf-8")

CLAUDE = """
# Claude Code Integration Task \u2014 Permit360

Integrate this website into the existing Kortex Digital portfolio.

Official brand: Permit360 by Kortex Digital.
Market: Israel.
Languages: Hebrew, Arabic, English and Russian.

Inspect the existing corporate website before making changes.
Preserve all existing portfolio products and functionality.

1. Add Permit360 to the corporate portfolio.
2. Prepare permit.kortexd.com as the public product website.
3. Preserve all four translated, server-readable pages.
4. Improve graphics using verified product screenshots where available.
5. Keep illustrative demonstrations clearly labeled.
6. Add localized pages for engineers, committees, building rights,
   application preparation, permit review, parcel search and security.
7. Integrate a real demo-request endpoint with consent and spam protection.
8. Implement parcel discovery only through verified authorized APIs.
9. Do not expose private application data or proprietary algorithms.
10. Validate reciprocal hreflang, canonical URLs and sitemap.
11. Add localized Open Graph preview images.
12. Test accessibility, responsive design and genuine RTL rendering.
13. Run Lighthouse and link validation.
14. Verify factual product claims against the actual Permit360 code.
15. Prepare Search Console and indexing configuration.
16. Document blockers and do not fabricate test results.
17. Do not modify production DNS without authorization.

Google and AI visibility must rely on original, useful,
crawlable and factually supported content rather than keyword stuffing.

Return the integrated code, test results and deployment instructions.
"""

(ROOT / "CLAUDE_UPDATE.md").write_text(CLAUDE, encoding="utf-8")

archive = Path("Permit360_Landing_Page_Release.zip")

with ZipFile(archive, "w", ZIP_DEFLATED) as z:
    for file in sorted(ROOT.rglob("*")):
        if file.is_file():
            z.write(file, file.relative_to(ROOT))

with ZipFile(archive) as z:
    assert z.testzip() is None
    print("ZIP generated:", archive.resolve())
    print("Files:", len(z.namelist()))
