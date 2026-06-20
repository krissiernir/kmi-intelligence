"""Pre-2021 KMÍ úthlutanir — recovered from the Internet Archive.

KMÍ's current site only hosts 2021–24 allocation PDFs; when they moved to a new CMS the older
years were dropped. The Wayback Machine still has the old per-year pages
(`.../uthlutanir-ur-kvikmyndasjodi/<year>`), where each year's allocations are HTML tables with the
SAME columns as today's PDFs: Verkefni · Handritshöfundur · Leikstjóri · Umsækjandi/Framleiðendur ·
Styrkur/samtals. We harvest those pages into data/raw/uthlutanir_archive/uth_<year>.html and parse
them here into the SAME allocation records the PDF parser emits → data/staged/allocations_archive.json.

This extends Zone 1 backwards so a pre-2021 film is no longer "before our window" by accident. The
KMÍ ledger remains the only source asserted; everything here carries source_id ...wayback +
confidence=needs_verification.

Run:  python -m kmi_intelligence.ingest.uthlutanir_archive
"""
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARCH = ROOT / "data" / "raw" / "uthlutanir_archive"
OUT = ROOT / "data" / "staged" / "allocations_archive.json"
WB = "http://web.archive.org"
OLD = "http://www.kvikmyndamidstod.is/kvikmyndasjodur/uthlutanir-ur-kvikmyndasjodi"
ARCHIVE_YEARS = range(2015, 2021)        # KMÍ's current CMS only hosts 2021+; older = Wayback only
UA = {"User-Agent": "kmi-intelligence/1.0 (research)"}

# The old pages put BOTH grant-family headers ("Framleiðslustyrkir:") and the format sub-sections
# ("Leiknar kvikmyndir - styrkir og vilyrði 2017") in <h2>. So every header is tried as a family
# first, then as a format. Substrings, matched against NFC-lowercased text.
FAMILY = {"framleiðslustyrk": "framleidsla", "þróunarstyrk": "throun", "handritsstyrk": "handrit",
          "eftirvinnslustyrk": "eftirvinnsla", "handrits- og þróunarstyrk": "throun"}
FORMAT = [("leiknar kvikmynd", "leikin_kvikmynd"), ("leiknar mynd", "leikin_kvikmynd"),
          ("leikið sjónvarp", "leikid_sjonvarp"), ("sjónvarpsefni", "leikid_sjonvarp"),
          ("heimildamynd", "heimildamynd"), ("heimildarmynd", "heimildamynd"),
          ("stuttmynd", "stuttmynd")]


def _clean(s: str) -> str:
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).replace("\xa0", " ").strip()
    return unicodedata.normalize("NFC", t)


def _amounts(s: str):
    """'65.000.000/72.800.000' -> (65000000, 72800000); single value -> (v, None)."""
    nums = re.findall(r"\d[\d.\s]*\d|\d", (s or "").replace("\xa0", " "))
    out = []
    for x in nums:
        d = re.sub(r"[^\d]", "", x)
        if len(d) >= 4:                       # ignore stray small numbers (footnote refs etc.)
            out.append(int(d))
    return (out[0] if out else None), (out[1] if len(out) > 1 else None)


def _col(hdr: list[str], *keys) -> int | None:
    return next((i for i, c in enumerate(hdr) if any(k in c for k in keys)), None)


def _cell(row: list[str], ci: dict, key: str):
    i = ci[key]
    return row[i] if i is not None and len(row) > i else None


def parse_file(path: Path, year: int) -> list[dict]:
    h = path.read_text(encoding="utf-8", errors="ignore")
    toks = []
    for m in re.finditer(r"<h[234][^>]*>(.*?)</h[234]>", h, re.S):
        toks.append((m.start(), "head", _clean(m.group(1))))
    for m in re.finditer(r"<table.*?</table>", h, re.S):
        toks.append((m.start(), "table", m.group(0)))
    toks.sort(key=lambda t: t[0])

    fam = fmt = None
    out: list[dict] = []
    for _, kind, val in toks:
        if kind == "head":
            low = val.lower()
            fam2 = next((v for k, v in FAMILY.items() if k in low), None)
            if fam2:                                  # a grant-family header → new family, reset format
                fam, fmt = fam2, None
            else:
                f2 = next((v for k, v in FORMAT if k in low), None)
                if f2:
                    fmt = f2
        elif kind == "table" and fam:
            rows = [[_clean(c) for c in re.findall(r"<t[dh].*?</t[dh]>", r, re.S)]
                    for r in re.findall(r"<tr.*?</tr>", val, re.S)]
            rows = [r for r in rows if any(r)]
            if len(rows) < 2:
                continue
            hdr = [c.lower() for c in rows[0]]
            ci = {"proj": _col(hdr, "verkefni"), "w": _col(hdr, "handrit"), "d": _col(hdr, "leikstjór"),
                  "co": _col(hdr, "umsækj", "framleið", "umsjón"),
                  "amt": _col(hdr, "styrkur", "upphæð", "samtals", "kr")}
            if ci["proj"] is None:
                continue
            for r in rows[1:]:
                if len(r) <= ci["proj"] or not r[ci["proj"]] or "samtals" in r[ci["proj"]].lower():
                    continue
                amt, tot = _amounts(_cell(r, ci, "amt") or "")
                co = _cell(r, ci, "co")
                out.append({
                    "year": year, "family": fam, "subtype": None, "format_track": fmt,
                    "source_id": f"src.uthlutanir_{year}_wayback", "raw_line": " | ".join(r),
                    "project_title": r[ci["proj"]], "writer": _cell(r, ci, "w"), "director": _cell(r, ci, "d"),
                    "applicant": co, "company": co, "amount_isk": amt, "total_isk": tot,
                    "commitments_json": "[]", "commitment_isk": None, "confidence": "needs_verification"})
    return out


def _get(url: str, timeout: int = 60) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def harvest() -> int:
    """Fetch the newest Wayback capture of each pre-2021 per-year page -> data/raw/uthlutanir_archive/.
    Raw HTML is kept local (gitignored, like all data/raw); re-runnable to regenerate provenance."""
    ARCH.mkdir(parents=True, exist_ok=True)
    for year in ARCHIVE_YEARS:
        cdx = (f"{WB}/cdx/search/cdx?url=kvikmyndamidstod.is/kvikmyndasjodur/"
               f"uthlutanir-ur-kvikmyndasjodi/{year}&output=json&fl=timestamp"
               f"&filter=statuscode:200&collapse=digest")
        try:
            rows = json.loads(_get(cdx))
        except Exception as e:                                                # noqa: BLE001
            print(f"  {year}: CDX error {e}")
            continue
        stamps = sorted(r[0] for r in rows[1:]) if len(rows) > 1 else []
        if not stamps:
            print(f"  {year}: no snapshot")
            continue
        snap = stamps[-1]                                                     # newest = most complete
        try:
            page = _get(f"{WB}/web/{snap}id_/{OLD}/{year}")
        except Exception as e:                                                # noqa: BLE001
            print(f"  {year}: fetch error {e}")
            continue
        (ARCH / f"uth_{year}.html").write_text(page, encoding="utf-8")
        markers = len(re.findall(r"(?i)framleiðslustyrk|þróunarstyrk", page))
        print(f"  {year}: snap={snap} {len(page)}b markers={markers}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "harvest":
        return harvest()
    if not ARCH.exists() or not any(ARCH.glob("uth_*.html")):
        print(f"no archive HTML in {ARCH} — run `... uthlutanir_archive harvest` first")
        return 1
    allocs, per_year = [], {}
    for f in sorted(ARCH.glob("uth_*.html")):
        m = re.search(r"uth_(\d{4})", f.name)
        if not m:
            continue
        year = int(m.group(1))
        recs = parse_file(f, year)
        per_year[year] = len(recs)
        allocs.extend(recs)
    OUT.write_text(json.dumps(allocs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"parsed {len(allocs)} pre-2021 allocations -> {OUT.relative_to(ROOT)}")
    for y in sorted(per_year):
        print(f"   {y}: {per_year[y]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
