"""IMDb integration — one module, four subcommands.

  datasets   FALLBACK: principal cast/crew from the official IMDb bulk datasets -> data/raw/imdb/
             (stdlib; runs in system python). Bulletproof but principals-only.
  enrich     PRIMARY: full credits via the `imdbinfo` library -> data/raw/imdb_full/
             (needs .venv-imdb). ~50 departments + companies + box office + AKAs.
  verify     validate our tconsts against IMDb title.basics (stdlib) -> data/raw/imdb/verify.json
  resolve    find tconsts for catalog titles that lack one (imdbinfo search) ->
             data/curated/imdb_links.json (+ a review queue); compile.py backfills these.

LICENSE/ToS: IMDb data (datasets AND scraped) is personal/non-commercial — kept LOCAL only,
NEVER committed, NEVER in export/. enrich/resolve are throttled + WAF-aware; persistent parser
failures are skipped, with the bulk datasets as the fallback.

Run:  python -m kmi_intelligence.ingest.imdb <datasets|enrich|verify|resolve>
      (enrich/resolve via .venv-imdb/bin/python).  Env: KMI_LIMIT, KMI_FORCE=1.
"""
from __future__ import annotations

import gzip
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "build" / "kmi.db"
OUT_DS = ROOT / "data" / "raw" / "imdb"
OUT_FULL = ROOT / "data" / "raw" / "imdb_full"
LINKS = ROOT / "data" / "curated" / "imdb_links.json"
REVIEW = ROOT / "data" / "staged" / "imdb_resolve_review.json"
BASE = "https://datasets.imdbws.com"
UA = {"User-Agent": "kmi-intelligence/1.0 (research)"}


def _tconsts(where="imdb_tconst LIKE 'tt%'"):
    c = sqlite3.connect(DB)
    return [r[0] for r in c.execute(f"SELECT DISTINCT imdb_tconst FROM title WHERE {where}")]


def _stream(name: str):
    """Yield decoded TSV dict rows from a gzipped IMDb dataset (streamed, nothing stored)."""
    req = urllib.request.Request(f"{BASE}/{name}", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp, gzip.GzipFile(fileobj=resp) as gz:
        header = gz.readline().decode("utf-8").rstrip("\n").split("\t")
        for raw in gz:
            yield dict(zip(header, raw.decode("utf-8").rstrip("\n").split("\t")))


def _norm(t):
    t = re.sub(r"\(.*?\)", " ", (t or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-záéíóúýþæöð]+", " ", t)).strip()


# ──────────────────────────────── datasets ────────────────────────────────
def run_datasets() -> int:
    OUT_DS.mkdir(parents=True, exist_ok=True)
    tconsts = set(_tconsts())
    print(f"{len(tconsts)} titles with an IMDb id")
    by_title, nconsts, seen = defaultdict(lambda: defaultdict(list)), set(), 0
    for row in _stream("title.principals.tsv.gz"):
        seen += 1
        tt = row.get("tconst")
        if tt in tconsts:
            n = row.get("nconst")
            nconsts.add(n)
            by_title[tt][row.get("category")].append({
                "nconst": n,
                "job": None if row.get("job") in ("\\N", None) else row.get("job"),
                "characters": None if row.get("characters") in ("\\N", None) else row.get("characters"),
                "ordering": int(row.get("ordering") or 0)})
        if seen % 5_000_000 == 0:
            print(f"  principals scanned {seen:,}; matched {len(by_title)}")
    print(f"principals: matched {len(by_title)} titles, {len(nconsts)} people")
    names, seen = {}, 0
    for row in _stream("name.basics.tsv.gz"):
        seen += 1
        if row.get("nconst") in nconsts:
            names[row["nconst"]] = {"name": row.get("primaryName"),
                                    "professions": (row.get("primaryProfession") or "").split(",")}
        if seen % 5_000_000 == 0:
            print(f"  names scanned {seen:,}; resolved {len(names)}")
    manifest = []
    for tt, cats in by_title.items():
        credits = {cat: [{**r, "name": names.get(r["nconst"], {}).get("name")}
                         for r in sorted(rows, key=lambda x: x["ordering"])]
                   for cat, rows in cats.items()}
        (OUT_DS / f"{tt}.json").write_text(json.dumps(
            {"imdb_tconst": tt, "credits": credits, "categories": sorted(credits)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({"imdb_tconst": tt, "categories": sorted(credits),
                         "crew_total": sum(len(v) for v in credits.values())})
    (OUT_DS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)} title files -> {OUT_DS.relative_to(ROOT)}")
    return 0


# ──────────────────────────────── verify ────────────────────────────────
def _toks(s):
    return set(re.sub(r"[^0-9a-záéíóúýþæöð ]", " ", (s or "").lower()).split())


def run_verify() -> int:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    ours = {r["imdb_tconst"]: {"title": r["title"], "year": r["year"]}
            for r in c.execute("SELECT imdb_tconst, title, year FROM title WHERE imdb_tconst LIKE 'tt%'")}
    print(f"validating {len(ours)} tconsts against IMDb title.basics")
    found = {}
    for f in _stream("title.basics.tsv.gz"):
        tt = f.get("tconst")
        if tt in ours:
            found[tt] = {"t": f.get("primaryTitle"), "o": f.get("originalTitle"),
                         "y": f.get("startYear"), "k": f.get("titleType")}
            if len(found) == len(ours):
                break
    report, suspects = [], []
    for tt, o in ours.items():
        b = found.get(tt)
        if not b:
            rec = {"tconst": tt, "our_title": o["title"], "status": "not_in_imdb"}
            suspects.append(rec)
        else:
            shared = _toks(o["title"]) & (_toks(b["t"]) | _toks(b["o"]))
            iy = None if b["y"] in ("\\N", "") else int(b["y"])
            ok = bool(shared) or not _toks(o["title"])
            rec = {"tconst": tt, "our_title": o["title"], "our_year": o["year"],
                   "imdb_title": b["t"], "imdb_year": iy, "imdb_type": b["k"], "title_match": ok}
            if not ok:
                rec["status"] = "TITLE_MISMATCH"
                suspects.append(rec)
        report.append(rec)
    (OUT_DS / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(report)} checked · {len(suspects)} suspect")
    for s in suspects[:40]:
        print(f"  {s.get('status')}: {s['tconst']} ours={s['our_title']!r}"
              + (f" vs IMDb={s.get('imdb_title')!r}" if s.get("imdb_title") else ""))
    return 0


# ──────────────────────────────── enrich (imdbinfo) ────────────────────────────────
SLEEP, WAF_BACKOFF, WAF_RETRIES = (1.0, 2.5), (30, 90), 3
JUNK_PREFIX = "amzn1.imdb"


def _person_rows(items):
    return [{"nconst": it.get("imdbId"), "name": it.get("name"), "job": it.get("job"),
             "characters": it.get("characters")} for it in (items or []) if isinstance(it, dict)]


def _company_rows(items):
    return [{"conmst": it.get("imdbId"), "name": it.get("name"),
             "notes": it.get("job") or it.get("notes")} for it in (items or []) if isinstance(it, dict)]


def _extract(m) -> dict:
    d = m.model_dump() if hasattr(m, "model_dump") else dict(m)
    crew = {cat: _person_rows(items) for cat, items in (d.get("categories") or {}).items()
            if not cat.startswith(JUNK_PREFIX) and _person_rows(items)}
    companies = {role: _company_rows(items) for role, items in (d.get("company_credits") or {}).items()
                 if _company_rows(items)}
    keys = ("title", "title_localized", "year", "kind", "countries", "genres", "release_date",
            "duration", "rating", "votes", "metacritic_rating", "production_budget",
            "worldwide_gross", "awards", "title_akas", "filming_locations", "storyline_keywords")
    rec = {k: d.get(k) for k in keys}
    rec.update({"imdb_tconst": d.get("imdbId"), "crew": crew, "companies": companies, "_source": "src.imdbinfo"})
    return rec


def run_enrich() -> int:
    from imdbinfo import get_movie
    from imdbinfo.exceptions import WAFError
    OUT_FULL.mkdir(parents=True, exist_ok=True)
    tconsts = sorted(set(_tconsts()))
    limit, force = int(os.environ.get("KMI_LIMIT", "0") or 0), os.environ.get("KMI_FORCE") == "1"
    if limit:
        tconsts = tconsts[:limit]
    print(f"enriching {len(tconsts)} titles via imdbinfo (force={force}) -> {OUT_FULL.relative_to(ROOT)}")

    def fetch(tt_num):
        for attempt in range(1, WAF_RETRIES + 1):
            try:
                return get_movie(tt_num)
            except WAFError:
                if attempt == WAF_RETRIES:
                    raise
                time.sleep(random.uniform(*WAF_BACKOFF) * attempt)

    manifest, failures, done, skipped = [], [], 0, 0
    for i, tt in enumerate(tconsts, 1):
        dest = OUT_FULL / f"{tt}.json"
        if dest.exists() and not force:
            skipped += 1
            continue
        try:
            rec = _extract(fetch(tt[2:] if tt.startswith("tt") else tt))
            rec["imdb_tconst"] = tt
            dest.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            done += 1
            manifest.append({"imdb_tconst": tt, "title": rec["title"], "departments": len(rec["crew"]),
                             "crew_total": sum(len(v) for v in rec["crew"].values()),
                             "companies": sum(len(v) for v in rec["companies"].values())})
        except Exception as e:
            failures.append({"imdb_tconst": tt, "error": f"{type(e).__name__}: {e}"})
            print(f"  [{i}/{len(tconsts)}] {tt} FAILED {type(e).__name__}: {str(e)[:70]}")
        time.sleep(random.uniform(*SLEEP))
    (OUT_FULL / "manifest_full.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_FULL / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done={done} skipped={skipped} failed={len(failures)} of {len(tconsts)}")
    return 0


# ──────────────────────────────── resolve (imdbinfo search) ────────────────────────────────
KIND_OK = {"film": {"movie", "tvMovie", "video"}, "documentary": {"movie", "tvMovie", "video"},
           "short": {"short", "tvShort"}, "series": {"tvSeries", "tvMiniSeries"}}
YEAR_TOL = {"film": 1, "documentary": 1, "short": 1, "series": 2}


def run_resolve() -> int:
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
    links = json.loads(LINKS.read_text()) if LINKS.exists() else []
    used = {l["imdb_tconst"] for l in links} | set(_tconsts())
    review, accepted = [], 0

    def search(q):
        for attempt in range(1, WAF_RETRIES + 1):
            try:
                res = search_title(q)
                return [cand.model_dump() if hasattr(cand, "model_dump") else cand
                        for cand in (getattr(res, "titles", None) or [])]
            except WAFError:
                if attempt == WAF_RETRIES:
                    return []
                time.sleep(random.uniform(*WAF_BACKOFF) * attempt)
            except Exception:
                return []

    for i, r in enumerate(rows, 1):
        nt, kind, yr = _norm(r["title"]), (r["kind"] or "film"), r["year"]
        ok_types, tol = KIND_OK.get(kind, KIND_OK["film"]), YEAR_TOL.get(kind, 1)
        best = None
        for d in search(r["title"]):
            tt = d.get("imdbId")
            if not tt or not str(tt).startswith("tt") or tt in used:
                continue
            exact = _norm(d.get("title")) == nt and bool(nt)
            kind_ok = d.get("kind") in ok_types
            year_ok = bool(d.get("year") and yr) and abs(d["year"] - yr) <= tol
            if exact and kind_ok and year_ok:
                best = {"title_norm": nt, "title": r["title"], "year": yr, "kind": kind,
                        "imdb_tconst": tt, "matched_title": d.get("title"), "matched_year": d.get("year"),
                        "matched_kind": d.get("kind"), "method": "exact_title+year+kind", "confidence": "high"}
                break
            if exact:
                review.append({"our": dict(r), "candidate": d,
                               "why": "year_mismatch" if kind_ok else "kind_mismatch"})
        if best:
            links.append(best)
            used.add(best["imdb_tconst"])
            accepted += 1
            print(f"  [{i}/{len(rows)}] ✓ {r['title']!r} ({yr}) -> {best['imdb_tconst']}")
        time.sleep(random.uniform(1.0, 2.2))
    LINKS.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    REVIEW.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"accepted {accepted} new links (total {len(links)}); parked {len(review)} for review")
    return 0


CMDS = {"datasets": run_datasets, "enrich": run_enrich, "verify": run_verify, "resolve": run_resolve}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in CMDS:
        print(f"usage: python -m kmi_intelligence.ingest.imdb {{{'|'.join(CMDS)}}}")
        return 2
    return CMDS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
