"""Validate our IMDb tconsts against IMDb's authoritative title.basics — catch WRONG links.

Our tconsts come from Wikipedia's IMDb links, which can be malformed. This streams the official
title.basics dataset, looks up each of our tconsts, and compares IMDb's title/year to ours.
- year differences are expected (Wikipedia uses Icelandic premiere; IMDb uses earliest year)
- a title MISMATCH (normalized titles share no words) ⇒ the link is probably wrong → flagged.

Output: data/raw/imdb/verify.json + a printed list of suspects. Stdlib only.
Run: python -m kmi_intelligence.ingest.imdb_verify
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "build" / "kmi.db"
OUT = ROOT / "data" / "raw" / "imdb"
URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
UA = {"User-Agent": "kmi-intelligence/1.0 (research)"}


def _toks(s):
    return set(re.sub(r"[^0-9a-záéíóúýþæöð ]", " ", (s or "").lower()).split())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    ours = {r["imdb_tconst"]: {"title": r["title"], "year": r["year"]}
            for r in c.execute("SELECT imdb_tconst, title, year FROM title WHERE imdb_tconst LIKE 'tt%'")}
    print(f"validating {len(ours)} tconsts against IMDb title.basics")

    found = {}
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp, gzip.GzipFile(fileobj=resp) as gz:
        hdr = gz.readline().decode("utf-8").rstrip("\n").split("\t")
        ix = {h: i for i, h in enumerate(hdr)}
        for raw in gz:
            f = raw.decode("utf-8").rstrip("\n").split("\t")
            tt = f[ix["tconst"]]
            if tt in ours:
                found[tt] = {"imdb_title": f[ix["primaryTitle"]], "imdb_original": f[ix["originalTitle"]],
                             "imdb_year": f[ix["startYear"]], "imdb_type": f[ix["titleType"]]}
                if len(found) == len(ours):
                    break

    report, suspects = [], []
    for tt, o in ours.items():
        b = found.get(tt)
        if not b:
            rec = {"tconst": tt, "our_title": o["title"], "status": "not_in_imdb"}
            suspects.append(rec)
        else:
            shared = _toks(o["title"]) & (_toks(b["imdb_title"]) | _toks(b["imdb_original"]))
            iy = None if b["imdb_year"] in ("\\N", "") else int(b["imdb_year"])
            title_ok = bool(shared) or not _toks(o["title"])
            rec = {"tconst": tt, "our_title": o["title"], "our_year": o["year"],
                   "imdb_title": b["imdb_title"], "imdb_year": iy, "imdb_type": b["imdb_type"],
                   "title_match": title_ok, "year_diff": (None if not (iy and o["year"]) else abs(iy - o["year"]))}
            if not title_ok:
                rec["status"] = "TITLE_MISMATCH"
                suspects.append(rec)
        report.append(rec)

    (OUT / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(report)} checked · {len(suspects)} suspect (wrong link / not found)")
    for s in suspects[:40]:
        if s.get("status") == "TITLE_MISMATCH":
            print(f"  WRONG? {s['tconst']}: ours={s['our_title']!r} ({s['our_year']}) vs IMDb={s['imdb_title']!r} ({s['imdb_year']})")
        else:
            print(f"  {s['status']}: {s['tconst']} {s['our_title']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
