"""Ingest Icelandic film lists from Wikipedia → data/staged/productions_films.json.

Wikipedia (is.wikipedia.org) is server-rendered, freely licensed (CC BY-SA), and uses a
{{Kvikmyndalisti}} template per title with titill / frumsýnd / leikstjóri / tenglar (the
tenglar field even carries the kvikmyndir.is id). This is the films source (the kvikmyndir.is
film search is Algolia-backed and not scraped). Same pattern works for the documentary/short
lists later — add them to PAGES.

Stdlib only (MediaWiki API). Run: python -m kmi_intelligence.ingest.wikipedia_films
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "wikipedia"
STAGED = ROOT / "data" / "staged" / "productions_films.json"
API = "https://is.wikipedia.org/w/api.php"
UA = {"User-Agent": "kmi-intelligence/1.0 (research; cross-reference with public KMÍ grant data)"}

# Wikipedia page title -> production kind. Add heimildarmyndir/stuttmyndir here later.
PAGES = {"Listi yfir íslenskar kvikmyndir": "film"}


def fetch_wikitext(page: str) -> str:
    q = urllib.parse.urlencode({"action": "parse", "page": page, "format": "json",
                                "prop": "wikitext", "formatversion": "2"})
    req = urllib.request.Request(f"{API}?{q}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["parse"]["wikitext"]


def _strip(s: str) -> str:
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)  # [[A|B]] -> B
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)            # [[A]] -> A
    s = re.sub(r"''+", "", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _rec(title, year, director, blob, kind):
    kid = re.search(r"kvikmyndir\.is/mynd/\?id=(\d+)", blob)
    imdb = re.search(r"(?:imdb\.com/title/|imdbtitle:)(tt?\d+)", blob)
    return {
        "kvik_id": int(kid.group(1)) if kid else None,
        "title": title, "year": year, "kind": kind, "status": None,
        "director": director or None,
        "imdb": imdb.group(1) if imdb else None,
        "url": f"https://kvikmyndir.is/mynd/?id={kid.group(1)}" if kid else None,
        "source": "src.wikipedia_is",
    }


def parse_films(wt: str, kind: str) -> list[dict]:
    out, seen = [], set()

    # (1) older decades use the {{Kvikmyndalisti}} template
    for b in re.split(r"\{\{\s*Kvikmyndalisti", wt)[1:]:
        body = b.split("\n}}")[0]
        f = {m.group(1).lower(): m.group(2).strip()
             for m in re.finditer(r"\|\s*([a-zA-ZáéíóúýþæöðÁÉÍÓÚÝÞÆÖÐ]+)\s*=\s*(.*)", body)}
        title = _strip(f.get("titill", ""))
        if not title:
            continue
        frum = f.get("frumsýnd", "") or f.get("frumsynd", "")
        ym = re.search(r"\b((?:19|20)\d{2})\b", frum) or re.search(r"\[\[((?:19|20)\d{2})\]\]", b)
        r = _rec(title, int(ym.group(1)) if ym else None,
                 _strip(f.get("leikstjóri", f.get("leikstjori", ""))), b, kind)
        out.append(r); seen.add(title.lower())

    # (2) the 2020s decade uses a wikitable: |Plakat |Frumsýning |Kvikmynd |Leikstjóri |Tenglar
    for tbl in re.findall(r"\{\|.*?\n\|\}", wt, flags=re.S):
        if "Frumsýning" not in tbl or "Kvikmynd" not in tbl:
            continue
        for rowblk in re.split(r"\n\|-", tbl):
            cells, cur = [], None
            for line in rowblk.split("\n"):
                if line[:2] in ("{|", "|+", "|}") or line.startswith("!"):
                    continue
                if line.startswith("|"):
                    if cur is not None:
                        cells.append(cur)
                    cur = line[1:].strip()
                elif cur is not None:
                    cur += " " + line.strip()
            if cur is not None:
                cells.append(cur)
            if len(cells) < 5:
                continue
            _, frum, title_c, dir_c, tenglar = cells[:5]
            title = _strip(title_c)
            if not title or title.lower() in seen:
                continue
            ym = re.search(r"\b((?:19|20)\d{2})\b", frum)
            out.append(_rec(title, int(ym.group(1)) if ym else None, _strip(dir_c), tenglar, kind))
            seen.add(title.lower())
    return out


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    for page, kind in PAGES.items():
        wt = fetch_wikitext(page)
        (RAW / (page.replace(" ", "_") + ".wikitext")).write_text(wt, encoding="utf-8")
        films = parse_films(wt, kind)
        rows.extend(films)
        print(f"{page}: {len(films)} {kind}s")
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    STAGED.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    wy = sum(1 for r in rows if r["year"])
    print(f"Wrote {len(rows)} productions ({wy} with year) -> {STAGED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
