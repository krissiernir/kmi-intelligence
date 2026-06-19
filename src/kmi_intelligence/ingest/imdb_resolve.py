"""Resolve catalog titles that have NO imdb_tconst → search IMDb (imdbinfo) and link them.

Targets the Wikipedia FILMS + kvikmyndir.is SERIES that lack a tconst (the úthlutanir project
names are intentionally excluded — many are in-development and noisy to match). For each, runs a
defensive imdbinfo.search_title and accepts a candidate ONLY when it is unambiguous:
  exact normalized-title match  AND  compatible titleType  AND  year within tolerance.
Anything weaker is parked for human review and NEVER auto-applied (same rule as fuzzy entity merges).

Outputs:
  data/curated/imdb_links.json        auto-accepted links (committed; read by compile.py to backfill)
  data/staged/imdb_resolve_review.json near-misses / ambiguous candidates for manual promotion

LICENSE/ToS: same as imdb_enrich — IMDb data is scraped, PRIVATE research only, never in export/.
Requires the imdbinfo venv:  .venv-imdb/bin/python -m kmi_intelligence.ingest.imdb_resolve
Env: KMI_LIMIT=20 (cap, for a dry run).
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "build" / "kmi.db"
LINKS = ROOT / "data" / "curated" / "imdb_links.json"
REVIEW = ROOT / "data" / "staged" / "imdb_resolve_review.json"

SLEEP = (1.0, 2.2)
WAF_BACKOFF = (30, 90)
WAF_RETRIES = 3

# our title.kind -> acceptable IMDb titleType set
KIND_OK = {
    "film": {"movie", "tvMovie", "video"},
    "documentary": {"movie", "tvMovie", "video"},
    "short": {"short", "tvShort"},
    "series": {"tvSeries", "tvMiniSeries"},
}
YEAR_TOL = {"film": 1, "documentary": 1, "short": 1, "series": 2}


def _norm(t):
    t = re.sub(r"\(.*?\)", " ", (t or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-záéíóúýþæöð]+", " ", t)).strip()


def _safe_search(search_title, q):
    """search_title throws on empty/odd result sets — treat any failure as no candidates."""
    try:
        res = search_title(q)
    except Exception:
        return []
    out = []
    for cand in (getattr(res, "titles", None) or []):
        d = cand.model_dump() if hasattr(cand, "model_dump") else cand
        if isinstance(d, dict):
            out.append(d)
    return out


def main() -> int:
    from imdbinfo import search_title
    from imdbinfo.exceptions import WAFError

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, title, year, kind FROM title "
        "WHERE source IN ('src.kvikmyndir_is','src.wikipedia_is') "
        "AND (imdb_tconst IS NULL OR imdb_tconst NOT LIKE 'tt%') AND year IS NOT NULL "
        "ORDER BY year DESC").fetchall()
    limit = int(os.environ.get("KMI_LIMIT", "0") or 0)
    if limit:
        rows = rows[:limit]
    print(f"resolving {len(rows)} catalog titles without a tconst")

    existing = {l["imdb_tconst"] for l in json.loads(LINKS.read_text())} if LINKS.exists() else set()
    used = set(existing)
    # also avoid colliding with tconsts already on titles
    used |= {r[0] for r in c.execute("SELECT imdb_tconst FROM title WHERE imdb_tconst LIKE 'tt%'")}

    links = json.loads(LINKS.read_text()) if LINKS.exists() else []
    review, accepted = [], 0

    for i, r in enumerate(rows, 1):
        nt, kind, yr = _norm(r["title"]), (r["kind"] or "film"), r["year"]
        ok_types = KIND_OK.get(kind, KIND_OK["film"])
        tol = YEAR_TOL.get(kind, 1)
        # WAF-aware search
        cands = []
        for attempt in range(1, WAF_RETRIES + 1):
            try:
                cands = _safe_search(search_title, r["title"])
                break
            except WAFError:
                if attempt == WAF_RETRIES:
                    break
                time.sleep(random.uniform(*WAF_BACKOFF) * attempt)

        best = None
        for d in cands:
            tt = d.get("imdbId")
            if not tt or not str(tt).startswith("tt") or tt in used:
                continue
            cn = _norm(d.get("title"))
            cy = d.get("year")
            ck = d.get("kind")
            exact = cn == nt and bool(nt)
            kind_ok = ck in ok_types
            year_ok = bool(cy and yr) and abs(cy - yr) <= tol
            if exact and kind_ok and year_ok:
                best = {"title_norm": nt, "title": r["title"], "year": yr, "kind": kind,
                        "imdb_tconst": tt, "matched_title": d.get("title"), "matched_year": cy,
                        "matched_kind": ck, "method": "exact_title+year+kind", "confidence": "high"}
                break
            if exact and kind_ok:  # title+kind but year off → review
                review.append({"our": dict(r), "candidate": d, "why": "year_mismatch"})
            elif exact:           # title only
                review.append({"our": dict(r), "candidate": d, "why": "kind_mismatch"})
        if best:
            links.append(best)
            used.add(best["imdb_tconst"])
            accepted += 1
            print(f"  [{i}/{len(rows)}] ✓ {r['title']!r} ({yr}) -> {best['imdb_tconst']} {best['matched_title']!r}")
        time.sleep(random.uniform(*SLEEP))

    LINKS.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    REVIEW.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\naccepted {accepted} new links (total {len(links)}) -> {LINKS.relative_to(ROOT)}")
    print(f"parked {len(review)} for review -> {REVIEW.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
