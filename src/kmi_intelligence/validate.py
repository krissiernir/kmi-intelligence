"""Pandera validation gate — reject bad rows at the staged→build boundary, before compile inserts.

Runs over the curated/staged inputs `compile.py` actually reads and checks types, non-null keys,
allowed ranges/categories. Catches the *class* of bug we hit by hand (e.g. an impossible figure, a
malformed source id) BEFORE it becomes a row in the DB / a fact / a stat. Exits non-zero on failure
so `make validate` can gate a build.

Lightweight + isolated: needs pandas+pandera (runs in .venv-er via `make validate`); the stdlib core
build does not import this. Read-only over JSON files.
Run: .venv-er/bin/python -m src.kmi_intelligence.validate   (or `make validate`)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUR = ROOT / "data" / "curated"
STG = ROOT / "data" / "staged"

GRANT_FAMILIES = {"handrit", "throun", "framleidsla", "eftirvinnsla", "endurgreidsla", "annad", None}


def _load(path: Path):
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(d, dict):  # lexicon wraps rows under "terms"
        d = d.get("terms", d)
    return d if isinstance(d, list) else None


def _schemas(pa, Column, Check, DataFrameSchema):
    SRC = Check.str_matches(r"^src\.")
    return {
        "data/staged/allocations.json": DataFrameSchema({
            "project_title": Column(str, Check.str_length(min_value=1)),
            "year": Column(int, Check.in_range(2018, 2026), coerce=True),
            "amount_isk": Column(float, Check.ge(0), nullable=True, coerce=True),
            "commitment_isk": Column(float, Check.ge(0), nullable=True, coerce=True),
            "family": Column(str, Check.isin(GRANT_FAMILIES), nullable=True),
            "source_id": Column(str, SRC),
        }, strict=False, coerce=True),
        "data/staged/productions_films.json": DataFrameSchema({
            "title": Column(str, Check.str_length(min_value=1)),
            "year": Column(float, Check.in_range(1900, 2030), nullable=True, coerce=True),
            "source": Column(str, SRC),
        }, strict=False, coerce=True),
        "data/staged/productions_series.json": DataFrameSchema({
            "title": Column(str, Check.str_length(min_value=1)),
            "year": Column(float, Check.in_range(1900, 2030), nullable=True, coerce=True),
            "source": Column(str, SRC),
        }, strict=False, coerce=True),
        "data/staged/companies_producers.json": DataFrameSchema({
            "name": Column(str, Check.str_length(min_value=1)),
            "is_sik_member": Column(int, Check.isin([0, 1]), coerce=True),
        }, strict=False, coerce=True),
        "data/curated/lexicon.json": DataFrameSchema({
            "is": Column(str, Check.str_length(min_value=1)),
            "en": Column(str, Check.str_length(min_value=1)),
            "category": Column(str, Check.str_length(min_value=1)),
        }, strict=False, coerce=True),
        "data/curated/imdb_links.json": DataFrameSchema({
            "imdb_tconst": Column(str, Check.str_matches(r"^tt\d+$")),
            "title_norm": Column(str, Check.str_length(min_value=1)),
            "year": Column(float, Check.in_range(1900, 2030), nullable=True, coerce=True),
        }, strict=False, coerce=True),
    }


def main() -> int:
    import os
    os.environ.setdefault("DISABLE_PANDERA_IMPORT_WARNING", "True")
    try:
        import pandas as pd
        try:
            import pandera.pandas as pa
            from pandera.pandas import Check, Column, DataFrameSchema
        except ImportError:
            import pandera as pa
            from pandera import Check, Column, DataFrameSchema
    except ImportError as e:
        print(f"validate needs pandas+pandera (run via .venv-er): {e}")
        return 2

    schemas = _schemas(pa, Column, Check, DataFrameSchema)
    total_fail = checked = 0
    print("Pandera gate — staged/curated inputs:")
    for rel, schema in schemas.items():
        rows = _load(ROOT / rel)
        if rows is None:
            print(f"  – {rel}  (absent, skipped)")
            continue
        checked += 1
        df = pd.DataFrame(rows)
        try:
            schema.validate(df, lazy=True)
            print(f"  ✓ {rel}  ({len(df)} rows)")
        except pa.errors.SchemaErrors as err:
            fc = err.failure_cases
            total_fail += len(fc)
            print(f"  ✗ {rel}  ({len(df)} rows) — {len(fc)} failures:")
            for _, row in fc.head(8).iterrows():
                print(f"      {row.get('column')}: {row.get('check')}  bad={row.get('failure_case')!r}")

    from . import log_event
    log_event("validate", datasets=checked, failures=total_fail)
    print(f"\n{checked} datasets checked · {total_fail} failures")
    if total_fail:
        print("FAILED — fix the staged/curated inputs before `make build`.")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
