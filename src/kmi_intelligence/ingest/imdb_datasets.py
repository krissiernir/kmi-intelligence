"""Fetch raw IMDb cast/crew for our titles from the OFFICIAL IMDb datasets → data/raw/imdb/<tt>.json.

Why not Cinemagoer/web: IMDb now serves a JS app and blocks scraping (HTTP 202/empty), so
Cinemagoer returns nothing and the fullcredits page can't be parsed. The official bulk datasets
(https://datasets.imdbws.com/, personal/non-commercial license) are static and reliable.

What this gets: principal cast + key crew per title — director, writer, producer, cinematographer
(DoP), editor, composer, production_designer, cast — each with the strong `nconst` key.
What it does NOT get: full department crew (gaffers, line producers, etc.) — those are not in the
public dataset; they need IMDb's authenticated API (a later, authorized path).

Streams + filters the gzips to our tconsts only (no multi-GB files stored). Stdlib only.
Run: python -m kmi_intelligence.ingest.imdb_datasets   (system python is fine)
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "build" / "kmi.db"
OUT = ROOT / "data" / "raw" / "imdb"
BASE = "https://datasets.imdbws.com"
UA = {"User-Agent": "kmi-intelligence/1.0 (research)"}


def stream(name: str):
    """Yield decoded TSV lines from a gzipped IMDb dataset, streaming (no full download stored)."""
    req = urllib.request.Request(f"{BASE}/{name}", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        with gzip.GzipFile(fileobj=resp) as gz:
            header = gz.readline().decode("utf-8").rstrip("\n").split("\t")
            for raw in gz:
                yield dict(zip(header, raw.decode("utf-8").rstrip("\n").split("\t")))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    tconsts = {r[0] for r in c.execute(
        "SELECT DISTINCT imdb_tconst FROM title WHERE imdb_tconst LIKE 'tt%'")}
    print(f"{len(tconsts)} titles with an IMDb id")

    # pass 1: title.principals -> credits for our titles + collect nconsts
    by_title = defaultdict(lambda: defaultdict(list))  # tconst -> category -> [rows]
    nconsts = set()
    seen = 0
    for row in stream("title.principals.tsv.gz"):
        seen += 1
        tt = row.get("tconst")
        if tt in tconsts:
            n = row.get("nconst")
            nconsts.add(n)
            by_title[tt][row.get("category")].append({
                "nconst": n,
                "job": None if row.get("job") in ("\\N", None) else row.get("job"),
                "characters": None if row.get("characters") in ("\\N", None) else row.get("characters"),
                "ordering": int(row.get("ordering") or 0),
            })
        if seen % 5_000_000 == 0:
            print(f"  principals scanned {seen:,}; matched titles so far {len(by_title)}")
    print(f"principals: matched {len(by_title)} titles, {len(nconsts)} people")

    # pass 2: name.basics -> names for the referenced people
    names = {}
    seen = 0
    for row in stream("name.basics.tsv.gz"):
        seen += 1
        if row.get("nconst") in nconsts:
            names[row["nconst"]] = {"name": row.get("primaryName"),
                                    "professions": (row.get("primaryProfession") or "").split(",")}
        if seen % 5_000_000 == 0:
            print(f"  names scanned {seen:,}; resolved {len(names)}")
    print(f"names: resolved {len(names)}")

    # write one JSON per title
    manifest = []
    for tt, cats in by_title.items():
        credits = {}
        for cat, rows in cats.items():
            credits[cat] = [{**r, "name": names.get(r["nconst"], {}).get("name")}
                            for r in sorted(rows, key=lambda x: x["ordering"])]
        (OUT / f"{tt}.json").write_text(
            json.dumps({"imdb_tconst": tt, "credits": credits, "categories": sorted(credits)},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({"imdb_tconst": tt, "categories": sorted(credits),
                         "crew_total": sum(len(v) for v in credits.values())})
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {len(manifest)} title files -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
