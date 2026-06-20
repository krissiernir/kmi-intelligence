"""Deep persons enrichment — the FULL IMDb credit list for key-role people (credits as data, not bios).

Bios are narrative/promotional and not a source of truth; what we actually want is every credit a
person holds — title, year, role/category, tconst, kind — including the international work our
919-title Icelandic catalog can't see. For each director/DOP/writer/producer who carries an IMDb id
we pull `imdbinfo.get_filmography` and store the complete per-category filmography.

Writes data/raw/person_credits/<nconst>.json (LOCAL only — IMDb data is never committed/exported, same
rule as the rest of the IMDb fold). compile folds these into person_imdb_credit.

Bonus identity check: if our spine credits someone as a director but their IMDb filmography has NO
director category, the nconst is probably MISLINKED (a same-name clash) — flagged, not trusted. (This
caught Valdimar Jóhannsson the Lamb director linked to a stunt performer's page.)

Run (needs .venv-imdb with imdbinfo):
  PYTHONPATH=src .venv-imdb/bin/python -m kmi_intelligence.ingest.persons_enrich [roles]
  env: KMI_LIMIT, KMI_FORCE=1.  default roles: director,cinematographer,writer,producer
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "build" / "kmi.db"
OUT = ROOT / "data" / "raw" / "person_credits"
SLEEP = (1.0, 2.0)
DEFAULT_ROLES = ["director", "cinematographer", "writer", "producer"]
# our credited role -> imdbinfo filmography category that would CONFIRM it (else: possible mislink)
ROLE_CAT = {"director": "director", "cinematographer": "cinematographer",
            "writer": "writer", "producer": "producer"}


def _people(roles):
    """[(nconst, name, {our_roles})] for everyone credited in `roles` who has an IMDb id."""
    c = sqlite3.connect(DB)
    out = {}
    rows = c.execute(
        "SELECT p.imdb_nconst, p.display_name, tc.role, p.credit_count FROM person p "
        "JOIN title_credit tc ON tc.person_id = p.id "
        f"WHERE tc.role IN ({','.join('?' * len(roles))}) AND p.imdb_nconst LIKE 'nm%' "
        "ORDER BY p.credit_count DESC", roles).fetchall()
    for nc, name, role, _ in rows:
        out.setdefault(nc, [name, set()])[1].add(role)
    return [(nc, v[0], v[1]) for nc, v in out.items()]


def _credit_rows(fg) -> tuple[list, dict]:
    """Flatten get_filmography -> [{category,title,tconst,year,kind}], + per-category counts."""
    rows, counts = [], {}
    for category, items in (fg or {}).items():
        counts[category] = len(items or [])
        for m in items or []:
            rows.append({"category": category, "title": getattr(m, "title", None),
                         "tconst": getattr(m, "imdbId", None), "year": getattr(m, "year", None),
                         "kind": getattr(m, "kind", None)})
    return rows, counts


def enrich(nconst, name, our_roles):
    from imdbinfo import get_filmography
    fg = get_filmography(nconst)
    credits, counts = _credit_rows(fg)
    # mislink check: a role we credit them with that has ZERO IMDb credits in that category
    missing = [r for r in our_roles if ROLE_CAT.get(r) and not counts.get(ROLE_CAT[r])]
    mismatch = ([f"credited as {sorted(our_roles)} but IMDb filmography has no "
                 f"{[ROLE_CAT[r] for r in missing]} credits (cats: {sorted(counts)})"]
                if missing else [])
    return {"nconst": nconst, "display_name": name, "our_roles": sorted(our_roles),
            "category_counts": counts, "credit_total": len(credits), "credits": credits,
            "id_mismatch": mismatch, "_source": "src.imdbinfo.filmography"}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    roles = argv[0].split(",") if argv else DEFAULT_ROLES
    OUT.mkdir(parents=True, exist_ok=True)
    people = _people(roles)
    limit, force = int(os.environ.get("KMI_LIMIT", "0") or 0), os.environ.get("KMI_FORCE") == "1"
    if limit:
        people = people[:limit]
    print(f"pulling full IMDb credits for {len(people)} people in roles {roles} -> {OUT.relative_to(ROOT)}")
    done = skipped = failed = flagged = total_credits = 0
    for i, (nc, name, rs) in enumerate(people, 1):
        dest = OUT / f"{nc}.json"
        if dest.exists() and not force:
            skipped += 1
            continue
        try:
            rec = enrich(nc, name, rs)
            dest.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            done += 1
            total_credits += rec["credit_total"]
            if rec["id_mismatch"]:
                flagged += 1
                print(f"  ⚠ MISLINK? {name} ({nc}): {rec['id_mismatch'][0]}")
            if i % 25 == 0:
                print(f"  [{i}/{len(people)}] {done} done · {total_credits} credits · {flagged} flagged")
        except Exception as e:                                                # noqa: BLE001
            failed += 1
            print(f"  [{i}/{len(people)}] {nc} {name!r} FAILED {type(e).__name__}: {str(e)[:60]}")
        time.sleep(random.uniform(*SLEEP))
    print(f"done={done} skipped={skipped} failed={failed} · {total_credits} credits · {flagged} mislinks flagged")
    from .. import log_event
    log_event("persons.enrich", people=done, credits=total_credits, flagged=flagged, failed=failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
