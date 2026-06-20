"""Klapptré.is — Icelandic film-industry news (Zone 3 corpus + landscape facts).

ONE file per source: the WordPress-API ingester (fetch → data/raw/klapptre/<id>.json) AND the
extractors compile.py uses to populate corpus_article + lx_* facts. Shared HTML cleaning lives in
textclean.py.

Klapptré runs WordPress, so we pull clean paginated JSON from /wp-json/wp/v2/posts (only /wp-admin
is robots-disallowed) instead of scraping HTML. Numbers come from the article's HTML TABLES; the
reviewed/awarded subject comes from the headline (Klapptré UPPERCASEs film titles or wraps them in
„…“). We never fabricate a review score — if it isn't explicit, it's null.

ZONE 3: journalistic, COPYRIGHTED. Kept LOCAL for private research only — never committed, never in
export/. Feeds tables that only READ Zone 1/2; grant tools never join them.

Ingest:  python -m kmi_intelligence.ingest.klapptre        (KMI_CATS=all to mirror whole site)
Extract: imported by compile.py (iter_articles / parse_admissions / parse_viewership / …)
"""
from __future__ import annotations

import glob
import html as _html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "raw" / "klapptre"
INDEX = ROOT / "data" / "staged" / "klapptre_index.json"
API = "https://klapptre.is/wp-json/wp/v2"
UA = {"User-Agent": "kmi-intelligence/1.0 (private film-research; contact krissiernir@reka.is)"}
SLEEP = 0.5

# Phase-1 structured "fact" categories (id -> name); promoted to lx_* in compile.py.
FACT_CATS = {108: "Aðsóknartölur", 1423: "Áhorfstölur", 106: "Gagnrýni",
             160: "Verðlaun", 161: "Tilnefningar"}
CAT = {"adsokn": 108, "ahorf": 1423, "review": 106, "award": 160, "nomination": 161}
CAT_NAMES = dict(FACT_CATS)


def load_categories() -> dict:
    """id -> category name, derived from the staged index (populated on a KMI_CATS=all run).
    Falls back to the 5 fact-category names when the full index isn't present."""
    m = dict(CAT_NAMES)
    if INDEX.exists():
        for a in json.loads(INDEX.read_text(encoding="utf-8")):
            for cid, nm in zip(a.get("categories", []), a.get("category_names", [])):
                if isinstance(nm, str) and not nm.isdigit():
                    m[cid] = nm
    return m

AWARD_HINTS = ["Edduverðlaun", "Eddan", "Edda", "Óskarsverðlaun", "Óskar", "Oscar", "Academy Award",
               "Golden Globe", "BAFTA", "Emmy", "Guldbagge", "Nordisk", "Cannes", "Berlin", "Berlinale",
               "Sundance", "Venice", "Feneyja", "Karlovy", "Tribeca", "Goya", "Grímuna", "Gríman",
               "Robert", "Amanda", "Annie", "César", "Locarno", "Toronto", "SXSW"]


# ───────────────────────── ingest (WordPress REST API) ─────────────────────────
def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")), r.headers


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def fetch_all_cat_names() -> dict:
    names, page = {}, 1
    while True:
        try:
            rows, _ = _get(f"{API}/categories?per_page=100&page={page}&_fields=id,name")
        except urllib.error.HTTPError:
            break
        if not rows:
            break
        for c in rows:
            names[c["id"]] = c["name"]
        page += 1
        time.sleep(SLEEP)
    return names


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    force = os.environ.get("KMI_FORCE") == "1"
    want_all = os.environ.get("KMI_CATS", "").lower() == "all"
    cat_names = fetch_all_cat_names() if want_all else dict(FACT_CATS)
    cats_param = "" if want_all else "&categories=" + ",".join(map(str, FACT_CATS))
    print(f"fetching Klapptré posts ({'ALL' if want_all else len(FACT_CATS)} categories) -> {OUT.relative_to(ROOT)}")

    fields = "id,date,modified,slug,link,title,excerpt,content,categories,tags,author"
    index, page, fetched, skipped = [], 1, 0, 0
    while True:
        url = f"{API}/posts?per_page=100&page={page}&_fields={fields}{cats_param}"
        try:
            rows, hdrs = _get(url)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise
        if not rows:
            break
        for p in rows:
            dest = OUT / f"{p['id']}.json"
            if not (dest.exists() and not force):
                dest.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
                fetched += 1
            else:
                skipped += 1
            index.append({
                "id": p["id"], "date": (p.get("date") or "")[:10], "slug": p.get("slug"),
                "link": p.get("link"), "title": _strip((p.get("title") or {}).get("rendered", "")),
                "excerpt": _strip((p.get("excerpt") or {}).get("rendered", ""))[:300],
                "categories": p.get("categories", []),
                "category_names": [cat_names.get(c, str(c)) for c in p.get("categories", [])],
                "tags": p.get("tags", []),
            })
        print(f"  page {page}/{hdrs.get('X-WP-TotalPages') or '?'}: {len(rows)} posts "
              f"(fetched {fetched}, skipped {skipped})")
        page += 1
        time.sleep(SLEEP)

    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(index)} posts indexed ({fetched} written, {skipped} cached) -> {INDEX.relative_to(ROOT)}")
    from .. import log_event
    log_event("ingest.klapptre", posts=len(index), written=fetched, cached=skipped,
              scope=("all" if want_all else "fact_cats"))
    return 0


# ───────────────────────── extract (used by compile.py) ─────────────────────────
def iter_articles():
    for f in sorted(glob.glob(str(OUT / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        title = _html.unescape(re.sub(r"<[^>]+>", "", (d.get("title") or {}).get("rendered", "")))
        yield {
            "id": d["id"], "date": (d.get("date") or "")[:10], "slug": d.get("slug"),
            "link": d.get("link"), "title": title.strip(),
            "cats": d.get("categories", []), "tags": d.get("tags", []),
            "html": (d.get("content") or {}).get("rendered", ""),
        }


def _int(s):
    """First number in a cell -> int. Takes only the leading token so '16,116 (14,293)' -> 16116
    and '90.954.270 kr.' -> 90954270 ('.'/',' are thousands separators here)."""
    m = re.search(r"\d[\d.,]*", s or "")
    return int(re.sub(r"[.,]", "", m.group(0))) if m else None


def _adm(s):
    """Admissions count with a sanity guard: Iceland's biggest films draw <~150k, so anything
    over 500k is a mislabeled ISK/gross figure — drop it rather than ship a false number."""
    v = _int(s)
    return v if (v is None or v <= 500_000) else None


def _pct(s):
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return float(m.group(0).replace(",", ".")) if m else None


def _tables(html):
    for tbl in re.findall(r"<table.*?</table>", html or "", re.S | re.I):
        rows = []
        for tr in re.findall(r"<tr.*?</tr>", tbl, re.S | re.I):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[dh].*?</t[dh]>", tr, re.S | re.I)]
            if any(cells):
                rows.append(cells)
        if rows:
            yield rows


def _hdr_index(header, *needles):
    for i, h in enumerate(header):
        if any(n in h.lower() for n in needles):
            return i
    return None


def parse_admissions(html):
    """-> [{film, week_admissions, total_admissions, gross_isk, weeks_in_release}] from box-office
    tables. Klapptré uses several layouts; we pick columns by header meaning, not position:
      total admissions = 'aðsókn'+'heildar'/'alls' (or the lone 'aðsókn' col on all-time lists)
      weekly admissions = a separate plain 'aðsókn' col when a total also exists
      gross_isk = a 'tekjur' (revenue) column, captured separately (never as admissions)."""
    out = []
    for rows in _tables(html):
        cols = [c.lower() for c in rows[0]]
        if not any(("mynd" in c or "heiti" in c) for c in cols):
            continue

        def find(pred):
            return next((i for i, h in enumerate(cols) if pred(h)), None)

        i_film = find(lambda h: "mynd" in h or "heiti" in h)
        i_weeks = find(lambda h: "vikur" in h or "vika" in h)
        i_gross = find(lambda h: "tekjur" in h)
        i_total = find(lambda h: "aðsókn" in h and ("heildar" in h or "alls" in h)) \
            or find(lambda h: h.strip().startswith("alls"))
        i_week = find(lambda h: "aðsókn" in h and not any(
            x in h for x in ("heildar", "alls", "staða", "tekjur")))
        if i_total is None:                       # no split -> the single col is the total
            i_total, i_week = i_week, None
        if i_film is None:
            continue
        for r in rows[1:]:
            if i_film >= len(r):
                continue
            film = r[i_film].strip()
            if not film or film.lower() in ("mynd", "kvikmynd", "heiti myndar"):
                continue
            out.append({
                "film": film,
                "week_admissions": _adm(r[i_week]) if i_week is not None and i_week < len(r) else None,
                "total_admissions": _adm(r[i_total]) if i_total is not None and i_total < len(r) else None,
                "gross_isk": _int(r[i_gross]) if i_gross is not None and i_gross < len(r) else None,
                "weeks_in_release": r[i_weeks].strip() if i_weeks is not None and i_weeks < len(r) else None,
            })
    return out


def parse_viewership(html):
    """-> [{title, channel, viewers, rating_pct, episodes}] from TV-viewership tables."""
    out = []
    for rows in _tables(html):
        hdr = rows[0]
        i_t = _hdr_index(hdr, "heiti", "þáttur", "efni")
        i_ch = _hdr_index(hdr, "stöð")
        i_v = _hdr_index(hdr, "áhorfend", "fjöldi áhorf")
        i_pct = _hdr_index(hdr, "áhorf%", "áhorf %", "%")
        i_ep = _hdr_index(hdr, "þátta", "fjöldi þátta")
        if i_t is None or i_v is None:
            continue
        for r in rows[1:]:
            if i_t >= len(r) or not r[i_t].strip():
                continue
            out.append({
                "title": r[i_t].strip(),
                "channel": r[i_ch].strip() if i_ch is not None and i_ch < len(r) else None,
                "viewers": _int(r[i_v]) if i_v < len(r) else None,
                "rating_pct": _pct(r[i_pct]) if i_pct is not None and i_pct < len(r) else None,
                "episodes": _int(r[i_ep]) if i_ep is not None and i_ep < len(r) else None,
            })
    return out


def review_outlet(headline: str):
    """Reviews are headlined 'OUTLET um TITLE: …' — return OUTLET when that shape is present."""
    m = re.match(r"\s*(.{2,40}?)\s+um\s+\S", headline or "")
    return m.group(1).strip() if m else None


def award_hint(text: str):
    for a in AWARD_HINTS:
        if a.lower() in (text or "").lower():
            return a
    return None


def name_candidates(headline):
    """Title-Case word runs (likely person names) from a headline, e.g. 'Jóhann Jóhannsson'."""
    return [m.strip() for m in re.findall(
        r"\b([A-ZÁÉÍÓÚÝÞÆÖÐ][a-záéíóúýþæöð]+(?:\s+[A-ZÁÉÍÓÚÝÞÆÖÐ][a-záéíóúýþæöð]+){1,3})", headline or "")]


def headline_subjects(title):
    """Candidate film/work names from a headline: „quoted“ names + runs of UPPERCASE words."""
    cands = list(re.findall(r"[„\"“]([^\"“”„]{2,60})[\"“”]", title or ""))
    for m in re.findall(r"\b([A-ZÁÉÍÓÚÝÞÆÖÐ][A-ZÁÉÍÓÚÝÞÆÖÐ0-9]+(?:\s+[A-ZÁÉÍÓÚÝÞÆÖÐ0-9&]+){0,5})\b", title or ""):
        w = m.strip()
        if len(w) >= 3 and w.lower() not in {"riff", "edda", "eddan", "kmí", "rúv"}:
            cands.append(w)
    seen, out = set(), []
    for c in cands:
        if c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
