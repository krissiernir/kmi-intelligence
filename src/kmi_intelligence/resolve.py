"""Entity-resolution candidate generation (Splink) — propose duplicate companies AND people.

Runs in the dedicated ER venv (.venv-er: splink + pandas 2.x + duckdb 1.1). Uses the rich graph
signal — name similarity (DIACRITIC-FOLDED, so Ólaf≈Olaf, Reykjavík≈Reykjavik) + SHARED works
(films for companies, titles for people) + type — to score candidate pairs, written ranked to
data/staged/merge_candidates.json as {"company": [...], "person": [...]}. It NEVER merges anything:
you confirm/reject in the one-page UI (app/review.py) -> data/curated/entity_merges.json, applied
deterministically by compile.py. Strong-key links (IMDb conmst/nconst) stay deterministic.

Run:  .venv-er/bin/python -m kmi_intelligence.resolve [companies|people|all]   (or `make resolve`)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "build" / "kmi.db"
CAND = ROOT / "data" / "staged" / "merge_candidates.json"
MERGES = ROOT / "data" / "curated" / "entity_merges.json"
THRESHOLD = 0.80


def _fold(s) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "").lower())
                   if not unicodedata.combining(ch))


def _decided(entity: str) -> set:
    """norm-pairs already merged or rejected for this entity type — skip them."""
    if not MERGES.exists():
        return set()
    d = json.loads(MERGES.read_text()).get(entity, {})
    pairs = set()
    for m in d.get("merges", []):
        for drop in m.get("drop", []):
            pairs.add(frozenset((m["keep"], drop)))
    for a, b in d.get("rejected", []):
        pairs.add(frozenset((a, b)))
    return pairs


def _load(c, entity: str):
    """Return (df, meta) for companies or people, with a diacritic-folded name + shared-works set."""
    import pandas as pd
    if entity == "company":
        rows = c.execute("SELECT id, name, name_norm, COALESCE(type,'?') type, COALESCE(is_sik_member,0) sik, "
                         "COALESCE(kmi_total_isk,0) isk FROM company WHERE name_norm!=''").fetchall()
        works = {}
        for cid, tid in c.execute("SELECT company_id, title_id FROM title_company"):
            works.setdefault(cid, set()).add(tid)
        meta = {r[0]: {"id": r[0], "name": r[1], "norm": r[2], "fold": _fold(r[2]), "type": r[3],
                       "sik": r[4], "isk": r[5], "rank": (r[4], r[5], len(works.get(r[0], ())))} for r in rows}
    else:  # person
        rows = c.execute("SELECT id, display_name, name_norm, COALESCE(imdb_nconst,'') nc, "
                         "COALESCE(credit_count,0) cc FROM person WHERE name_norm!=''").fetchall()
        works = {}
        for pid, tid in c.execute("SELECT person_id, title_id FROM title_credit"):
            works.setdefault(pid, set()).add(tid)
        meta = {r[0]: {"id": r[0], "name": r[1], "norm": r[2], "fold": _fold(r[2]),
                       "nconst": r[3], "cc": r[4], "rank": (1 if r[3] else 0, r[4], len(works.get(r[0], ())))}
                for r in rows}
    df = pd.DataFrame([{"unique_id": k, "name_fold": m["fold"], "works": sorted(works.get(k, ()))}
                       for k, m in meta.items()])
    for k, m in meta.items():
        m["works"] = works.get(k, set())
    return df, meta


def _dedupe(entity: str, df, meta) -> list:
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on
    settings = SettingsCreator(
        link_type="dedupe_only", probability_two_random_records_match=2e-4,
        comparisons=[cl.JaroWinklerAtThresholds("name_fold", [0.92, 0.85]),
                     cl.ArrayIntersectAtSizes("works", [2, 1])],
        blocking_rules_to_generate_predictions=[block_on("substr(name_fold,1,4)"),
                                                "len(list_intersect(l.works, r.works)) >= 2"])
    lk = Linker(df, settings, db_api=DuckDBAPI())
    lk.training.estimate_u_using_random_sampling(max_pairs=1e6)
    lk.training.estimate_parameters_using_expectation_maximisation(block_on("substr(name_fold,1,4)"))
    lk.training.estimate_parameters_using_expectation_maximisation("len(list_intersect(l.works, r.works)) >= 2")
    pred = lk.inference.predict(threshold_match_probability=THRESHOLD).as_pandas_dataframe()

    decided = _decided(entity)
    out = []
    for _, r in pred.iterrows():
        a, b = meta.get(r["unique_id_l"]), meta.get(r["unique_id_r"])
        if not a or not b or a["norm"] == b["norm"]:
            continue
        if frozenset((a["norm"], b["norm"])) in decided:
            continue
        keep, drop = (a, b) if a["rank"] >= b["rank"] else (b, a)
        rec = {"entity_type": entity, "score": round(float(r["match_probability"]), 4),
               "keep_id": keep["id"], "keep_name": keep["name"], "keep_norm": keep["norm"],
               "drop_id": drop["id"], "drop_name": drop["name"], "drop_norm": drop["norm"],
               "shared": len(keep["works"] & drop["works"]),
               "keep_works": len(keep["works"]), "drop_works": len(drop["works"])}
        if entity == "person":
            rec["keep_nconst"], rec["drop_nconst"] = keep.get("nconst"), drop.get("nconst")
        out.append(rec)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


_PATRONYMIC = ("son", "dóttir", "dottir", "sen", "bur")


def _prefix_candidates(entity, meta, decided) -> list:
    """Deterministic catch for name-extension splits Splink misses: a short name that is a word-prefix
    of a longer one where the extra token is a patronymic (Olaf de Fleur ⊂ Olaf de Fleur Johannesson)
    OR the two share a work. These often have DISJOINT works (grants-side vs IMDb-side), so name is
    the only signal — surfaced for review, never auto-merged."""
    fold_to = {}
    for m in meta.values():
        fold_to.setdefault(m["fold"], m)  # one representative per folded name
    folds = sorted(f for f in fold_to if len(f.split()) >= 2)
    out, seen = [], set()
    for a in folds:
        for b in folds:
            if b == a or not b.startswith(a + " "):
                continue
            extra = b[len(a) + 1:].split()
            ma, mb = fold_to[a], fold_to[b]
            patronymic = len(extra) == 1 and extra[0].endswith(_PATRONYMIC)
            shared = len(ma["works"] & mb["works"])
            if not (patronymic or shared):
                continue
            pair = frozenset((ma["norm"], mb["norm"]))
            if pair in decided or pair in seen:
                continue
            seen.add(pair)
            keep, drop = (mb, ma) if mb["rank"] >= ma["rank"] else (ma, mb)
            rec = {"entity_type": entity, "score": 0.9 if patronymic else 0.84,
                   "keep_id": keep["id"], "keep_name": keep["name"], "keep_norm": keep["norm"],
                   "drop_id": drop["id"], "drop_name": drop["name"], "drop_norm": drop["norm"],
                   "shared": shared, "keep_works": len(keep["works"]), "drop_works": len(drop["works"]),
                   "method": "name_prefix+patronymic" if patronymic else "name_prefix+shared_work"}
            if entity == "person":
                rec["keep_nconst"], rec["drop_nconst"] = keep.get("nconst"), drop.get("nconst")
            out.append(rec)
    return out


def main(argv=None) -> int:
    mode = (argv or sys.argv[1:] or ["companies"])[0]
    entities = {"companies": ["company"], "people": ["person"], "all": ["company", "person"]}.get(mode)
    if not entities:
        print("usage: resolve [companies|people|all]")
        return 2
    c = sqlite3.connect(DB)
    existing = json.loads(CAND.read_text()) if CAND.exists() else {}
    if not isinstance(existing, dict):
        existing = {}  # migrate from the old flat (company-only) format
    for entity in entities:
        df, meta = _load(c, entity)
        print(f"{len(df)} {entity}s; running Splink dedupe…")
        decided = _decided(entity)
        cands = _dedupe(entity, df, meta)
        seen = {frozenset((x["keep_norm"], x["drop_norm"])) for x in cands}
        extra = [x for x in _prefix_candidates(entity, meta, decided)
                 if frozenset((x["keep_norm"], x["drop_norm"])) not in seen]
        cands = sorted(cands + extra, key=lambda x: x["score"], reverse=True)
        existing[entity] = cands
        print(f"  {len(cands)} undecided {entity} candidate pairs (Splink + {len(extra)} name-prefix)")
    CAND.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote -> {CAND.relative_to(ROOT)}   (review: `make review`)")
    from . import log_event
    log_event("resolve", **{f"{e}_candidates": len(existing.get(e, [])) for e in entities})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
