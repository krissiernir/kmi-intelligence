"""Ingest the kvikmyndir.is Icelandic production catalog → data/staged/productions.json.

Purpose: a production catalog to cross-reference against the KMÍ funding ledger — e.g. which
series reached audiences WITHOUT a KMÍ grant. kvikmyndir.is is a third-party, community film/TV
database (confidence: needs_verification).

Scope (for now): Icelandic SERIES are server-rendered at /islenskir-thaettir/ (full list). The
films catalog is behind Algolia search (not scraped here — follow-up). Pass --details to also
crawl each title's /mynd/?id= page for director / where-it-aired / genres (polite, cached).

Stdlib only. Run:  python -m kmi_intelligence.ingest.kvikmyndir [--details]
"""
from __future__ import annotations

import html as ihtml
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "kvikmyndir"
DETAILS = RAW / "details"
STAGED = ROOT / "data" / "staged" / "productions_series.json"
UA = {"User-Agent": "kmi-intelligence/1.0 (research; cross-reference with public KMÍ grant data)"}
SERIES_URL = "https://kvikmyndir.is/islenskir-thaettir/"
DETAIL_URL = "https://kvikmyndir.is/mynd/?id={}"

PLATFORMS = {
    "RÚV": ["rúv", "ruv"], "Stöð 2": ["stöð 2", "stod 2", "stöð2"],
    "Sjónvarp Símans": ["símans", "sjónvarp símans", "síminn"], "Netflix": ["netflix"],
    "Viaplay": ["viaplay"], "Disney+": ["disney+"], "Amazon Prime": ["prime video"],
}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_list(html: str, kind: str) -> list[dict]:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    out, seen = [], set()
    for mid, inner in re.findall(r'<a[^>]+href="[^"]*mynd/\?id=(\d+)"[^>]*>(.*?)</a>', html, flags=re.S):
        if mid in seen:
            continue
        alt = re.search(r'alt="([^"]+)"', inner)
        text = ihtml.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner))).strip()
        title = ihtml.unescape(alt.group(1)).replace("\xad", "").strip() if alt else None
        if not title:
            continue
        seen.add(mid)
        ym = re.search(r"\b(19|20)\d{2}\b", text)
        status = next((s for s in ("Yfirstandandi", "Nýlegt", "Lokið", "Væntanlegt") if s.lower() in text.lower()), None)
        out.append({"kvik_id": int(mid), "title": title, "year": int(ym.group()) if ym else None,
                    "kind": kind, "status": status, "url": DETAIL_URL.format(mid), "source": "src.kvikmyndir_is"})
    return out


def fetch_detail(mid: int) -> str:
    DETAILS.mkdir(parents=True, exist_ok=True)
    cache = DETAILS / f"{mid}.html"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    html = get(DETAIL_URL.format(mid))
    cache.write_text(html, encoding="utf-8")
    time.sleep(0.4)  # be polite
    return html


def parse_detail(html: str) -> dict:
    """Extract only what's reliable from a detail page.

    NOTE: director and where-it-aired are NOT extracted — the detail pages carry global
    navigation/filter chrome that lists every platform and a "more by this director" section,
    so keyword/regex scans produce false positives. Reliable structured extraction of those
    fields is a follow-up (needs targeting the specific detail block). og:type is a real meta
    tag but mislabels some series as video.movie, so we keep it only as a weak hint.
    """
    d = {}
    ot = re.search(r'og:type" content="([^"]+)"', html)
    if ot:
        d["og_type_hint"] = ot.group(1)
    return d


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    want_details = "--details" in sys.argv

    series_html = get(SERIES_URL)
    (RAW / "series_list.html").write_text(series_html, encoding="utf-8")
    rows = parse_list(series_html, "series")
    print(f"Parsed {len(rows)} series from {SERIES_URL}")

    if want_details:
        print("Crawling detail pages (cached, ~0.4s each)…")
        for i, r in enumerate(rows, 1):
            try:
                r.update(parse_detail(fetch_detail(r["kvik_id"])))
            except Exception as e:  # noqa: BLE001
                print(f"  detail {r['kvik_id']} failed: {e}")
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}")
        with_where = sum(1 for r in rows if r.get("where_shown"))
        print(f"  enriched; {with_where} have a detected platform")

    STAGED.parent.mkdir(parents=True, exist_ok=True)
    STAGED.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} productions -> {STAGED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
