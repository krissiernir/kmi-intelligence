"""Parse the mirrored KMÍ sitemap (data/raw/site) into structured data + corpus.

The whole site (342 pages) was mirrored by fetch.py --sitemap; only the grant pages were ever
turned into structured data. This finishes the job:
  • ahorf/*          -> lx_viewership facts (KMÍ's authoritative annual TV-áhorf tables)
  • frettir/*, kvikmyndamenning/*, um/* -> corpus_article (KMÍ news/culture/about, Zone 3)

Content is taken from <main id="main"> so the (identical) nav/header/footer chrome is dropped —
the lesson from the kvikmyndir scrape. Reuses klapptre's viewership table parser (same columns).
Source id: src.kmi_sitemap_mirror. Stdlib only; imported by compile.py's Zone 3 build.
"""
from __future__ import annotations

import glob
import html as _html
import re
from pathlib import Path

from . import klapptre  # reuse parse_viewership (Heiti/Stöð/þættir/sýningar/Áhorf%/Áhorfendur)
from .textclean import to_text

ROOT = Path(__file__).resolve().parents[3]
SITE = ROOT / "data" / "raw" / "site"

# filename prefix -> section. Files are like "frettir_<slug>.html", "ahorf_a_..._2020.html".
SECTIONS = ("ahorf", "frettir", "kvikmyndamenning", "um", "kvikmyndagerd")


def _section(name: str) -> str:
    for s in SECTIONS:
        if name.startswith(s):
            return s
    return "other"


def _main(html: str) -> str:
    """Just the article body: <main id="main"> … </main> (falls back to whole doc)."""
    m = re.search(r'<main[^>]*id="main"[^>]*>(.*?)</main>', html, re.S | re.I)
    return m.group(1) if m else html


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape((s or "").replace("\xad", ""))).strip()


def _title(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    return _clean(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""


def _date(html: str) -> str:
    m = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", html)  # dd.mm.yyyy
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def _year(name: str, title: str, date: str) -> int | None:
    for s in (date[:4], *re.findall(r"\b(20\d\d)\b", name + " " + title)):
        if s and s.isdigit():
            return int(s)
    return None


def iter_pages():
    """Yield one record per mirrored KMÍ HTML page (skip the .txt twins + sitemap/manifest)."""
    for f in sorted(glob.glob(str(SITE / "*.html"))):
        name = Path(f).stem
        if name in ("sitemap", "manifest", "index"):
            continue
        html = open(f, encoding="utf-8").read()
        main = _main(html)
        title = _title(html) or _clean(name.replace("_", " "))
        date = _date(main)
        yield {"name": name, "section": _section(name), "title": title, "date": date,
               "year": _year(name, title, date), "main_html": main, "text": to_text(main)}


def parse_viewership(main_html: str):
    """KMÍ áhorf tables -> viewership rows (delegates to the Klapptré parser; same columns)."""
    return klapptre.parse_viewership(main_html)
