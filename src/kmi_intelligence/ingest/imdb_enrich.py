"""Rich IMDb enrichment via `imdbinfo` (full credits page) → data/raw/imdb_full/<tt>.json.

Why this exists alongside imdb_datasets.py:
  - imdb_datasets.py uses the OFFICIAL bulk datasets → bulletproof, but ONLY principals
    (director/writer/producer/DoP/editor/cast — ~10 categories, capped).
  - imdbinfo parses IMDb's modern embedded JSON → the FULL credits page: ~50 departments
    incl. camera/sound/editorial/make-up/VFX/assistant-director and (when IMDb lists them)
    gaffers & line producers, PLUS company_credits (production/sales/distribution),
    awards tallies, worldwide gross, production budget, AKAs.
  imdbinfo strictly dominates on content, so it is the PRIMARY enrichment; the dataset files
  remain a fallback for titles imdbinfo can't parse.

LICENSE / ToS: imdbinfo is MIT (the code); the DATA is still IMDb's, scraped. Treat exactly
like the bulk datasets — keep under data/raw/ for PRIVATE research only, and NEVER ship any
IMDb-derived field in the committed export/. Be polite: throttle + back off on WAF.

Robustness: some titles raise a persistent parser KeyError (e.g. 'rowTitle'); some calls hit
IMDb's WAF. We retry WAF with backoff and skip hard parse failures, logging both.

Requires the imdbinfo venv:  .venv-imdb/bin/python -m kmi_intelligence.ingest.imdb_enrich
Options (env): KMI_LIMIT=5 (cap titles, for validation), KMI_FORCE=1 (re-fetch existing).
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "build" / "kmi.db"
OUT = ROOT / "data" / "raw" / "imdb_full"

# politeness / resilience
SLEEP = (1.0, 2.5)          # random delay between titles
WAF_BACKOFF = (30, 90)      # seconds to wait when WAF-blocked
WAF_RETRIES = 3

# IMDb internal category ids the parser leaves unmapped — not real departments
JUNK_PREFIX = "amzn1.imdb"


def _person_rows(items):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        out.append({"nconst": it.get("imdbId"), "name": it.get("name"),
                    "job": it.get("job"), "characters": it.get("characters")})
    return out


def _company_rows(items):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        out.append({"conmst": it.get("imdbId"), "name": it.get("name"),
                    "notes": it.get("job") or it.get("notes")})
    return out


def extract(m) -> dict:
    """Map an imdbinfo movie model → our compact raw record."""
    d = m.model_dump() if hasattr(m, "model_dump") else dict(m)
    crew = {}
    for cat, items in (d.get("categories") or {}).items():
        if cat.startswith(JUNK_PREFIX):
            continue
        rows = _person_rows(items)
        if rows:
            crew[cat] = rows
    companies = {}
    for role, items in (d.get("company_credits") or {}).items():
        rows = _company_rows(items)
        if rows:
            companies[role] = rows
    return {
        "imdb_tconst": d.get("imdbId"),
        "title": d.get("title"),
        "title_localized": d.get("title_localized"),
        "year": d.get("year"),
        "kind": d.get("kind"),
        "countries": d.get("countries"),
        "genres": d.get("genres"),
        "release_date": d.get("release_date"),
        "duration": d.get("duration"),
        "rating": d.get("rating"),
        "votes": d.get("votes"),
        "metacritic_rating": d.get("metacritic_rating"),
        "production_budget": d.get("production_budget"),
        "worldwide_gross": d.get("worldwide_gross"),
        "awards": d.get("awards"),
        "title_akas": d.get("title_akas"),
        "filming_locations": d.get("filming_locations"),
        "storyline_keywords": d.get("storyline_keywords"),
        "crew": crew,
        "companies": companies,
        "_source": "src.imdbinfo",
    }


def fetch_one(get_movie, tt_num: str):
    """get_movie with WAF backoff; returns model or raises the final exception."""
    from imdbinfo.exceptions import WAFError  # local import (venv-only dep)
    for attempt in range(1, WAF_RETRIES + 1):
        try:
            return get_movie(tt_num)
        except WAFError:
            if attempt == WAF_RETRIES:
                raise
            wait = random.uniform(*WAF_BACKOFF) * attempt
            print(f"    WAF block, backing off {wait:.0f}s (attempt {attempt})")
            time.sleep(wait)


def main() -> int:
    from imdbinfo import get_movie  # noqa: import here so non-venv pythons fail loudly

    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    tconsts = sorted({r[0] for r in c.execute(
        "SELECT DISTINCT imdb_tconst FROM title WHERE imdb_tconst LIKE 'tt%'")})
    limit = int(os.environ.get("KMI_LIMIT", "0") or 0)
    force = os.environ.get("KMI_FORCE") == "1"
    if limit:
        tconsts = tconsts[:limit]
    print(f"enriching {len(tconsts)} titles via imdbinfo "
          f"(force={force}) -> {OUT.relative_to(ROOT)}")

    manifest, failures, done, skipped = [], [], 0, 0
    for i, tt in enumerate(tconsts, 1):
        dest = OUT / f"{tt}.json"
        if dest.exists() and not force:
            skipped += 1
            continue
        try:
            m = fetch_one(get_movie, tt[2:] if tt.startswith("tt") else tt)
            rec = extract(m)
            rec["imdb_tconst"] = tt  # canonical (search/get can echo numeric)
            dest.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            done += 1
            crew_n = sum(len(v) for v in rec["crew"].values())
            comp_n = sum(len(v) for v in rec["companies"].values())
            manifest.append({"imdb_tconst": tt, "title": rec["title"],
                             "departments": len(rec["crew"]), "crew_total": crew_n,
                             "companies": comp_n, "gross": rec["worldwide_gross"]})
            print(f"  [{i}/{len(tconsts)}] {tt} {rec['title']!r}: "
                  f"{len(rec['crew'])} depts / {crew_n} crew / {comp_n} cos")
        except Exception as e:  # parser KeyError, WAF exhausted, network, etc.
            failures.append({"imdb_tconst": tt, "error": f"{type(e).__name__}: {e}"})
            print(f"  [{i}/{len(tconsts)}] {tt} FAILED {type(e).__name__}: {str(e)[:80]}")
        time.sleep(random.uniform(*SLEEP))

    (OUT / "manifest_full.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndone={done} skipped(existing)={skipped} failed={len(failures)} "
          f"of {len(tconsts)} -> {OUT.relative_to(ROOT)}")
    if failures:
        print(f"  see failures.json ({len(failures)}) — bulk-dataset files remain the fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
