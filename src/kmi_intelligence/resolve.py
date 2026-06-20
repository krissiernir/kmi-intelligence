"""Entity-resolution candidate generation (Splink) — propose duplicate companies for review.

Runs in the dedicated ER venv (.venv-er: splink + pandas 2.x + duckdb 1.1). Uses the rich graph
signal (name similarity + SHARED FILMS + type), scores each candidate pair, and writes a ranked
list to data/staged/merge_candidates.json. It NEVER merges anything — confirmation happens in the
one-page review UI (app/review.py) which writes data/curated/entity_merges.json, applied
deterministically by compile.py. Strong-key links (IMDb conmst) are out of scope here.

Already-decided pairs (confirmed merges or rejects in entity_merges.json) are skipped.
Run:  .venv-er/bin/python -m kmi_intelligence.resolve   (or `make resolve`)
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "build" / "kmi.db"
CAND = ROOT / "data" / "staged" / "merge_candidates.json"
MERGES = ROOT / "data" / "curated" / "entity_merges.json"
THRESHOLD = 0.80


def _cnorm(s):  # must match compile.py's company normalizer
    s = re.sub(r"\b(ehf|slf|sf|hf|ses)\b", " ", (s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-záéíóúýþæöð]+", " ", s)).strip()


def _decided() -> set:
    """norm-pairs already merged or rejected — skip them."""
    if not MERGES.exists():
        return set()
    d = json.loads(MERGES.read_text())
    pairs = set()
    for m in d.get("merges", []):
        for drop in m.get("drop", []):
            pairs.add(frozenset((m["keep"], drop)))
    for a, b in d.get("rejected", []):
        pairs.add(frozenset((a, b)))
    return pairs


def main() -> int:
    import pandas as pd
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    c = sqlite3.connect(DB)
    comp = c.execute("SELECT id, name, name_norm, COALESCE(type,'?') type, COALESCE(is_sik_member,0) sik, "
                     "COALESCE(kmi_total_isk,0) isk FROM company WHERE name_norm!=''").fetchall()
    films = {}
    for cid, tid in c.execute("SELECT company_id, title_id FROM title_company"):
        films.setdefault(cid, set()).add(tid)
    meta = {r[0]: {"id": r[0], "name": r[1], "norm": r[2], "type": r[3], "sik": r[4], "isk": r[5],
                   "films": films.get(r[0], set())} for r in comp}
    df = pd.DataFrame([{"unique_id": cid, "name_norm": m["norm"], "type": m["type"],
                        "films": sorted(m["films"])} for cid, m in meta.items()])
    print(f"{len(df)} companies; running Splink dedupe…")

    settings = SettingsCreator(
        link_type="dedupe_only", probability_two_random_records_match=2e-4,
        comparisons=[cl.JaroWinklerAtThresholds("name_norm", [0.92, 0.85]),
                     cl.ArrayIntersectAtSizes("films", [2, 1]), cl.ExactMatch("type")],
        blocking_rules_to_generate_predictions=[block_on("substr(name_norm,1,3)"),
                                                "len(list_intersect(l.films, r.films)) >= 2"])
    lk = Linker(df, settings, db_api=DuckDBAPI())
    lk.training.estimate_u_using_random_sampling(max_pairs=1e6)
    lk.training.estimate_parameters_using_expectation_maximisation(block_on("substr(name_norm,1,3)"))
    lk.training.estimate_parameters_using_expectation_maximisation("len(list_intersect(l.films, r.films)) >= 2")
    pred = lk.inference.predict(threshold_match_probability=THRESHOLD).as_pandas_dataframe()

    decided = _decided()
    out = []
    for _, r in pred.iterrows():
        a, b = meta.get(r["unique_id_l"]), meta.get(r["unique_id_r"])
        if not a or not b or a["norm"] == b["norm"]:
            continue
        if frozenset((a["norm"], b["norm"])) in decided:
            continue
        shared = sorted(a["films"] & b["films"])
        # default canonical = SÍK member, else more funding, else more films
        keep, drop = ((a, b) if (a["sik"], a["isk"], len(a["films"])) >= (b["sik"], b["isk"], len(b["films"])) else (b, a))
        out.append({
            "entity_type": "company", "score": round(float(r["match_probability"]), 4),
            "keep_id": keep["id"], "keep_name": keep["name"], "keep_norm": keep["norm"],
            "drop_id": drop["id"], "drop_name": drop["name"], "drop_norm": drop["norm"],
            "shared_films": len(shared), "keep_films": len(keep["films"]), "drop_films": len(drop["films"]),
            "keep_sik": keep["sik"], "keep_isk": keep["isk"], "drop_isk": drop["isk"],
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    CAND.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(out)} undecided candidate pairs (>= {THRESHOLD}) -> {CAND.relative_to(ROOT)}")
    print("review them: `make review`  (writes data/curated/entity_merges.json; applied by `make build`)")
    from . import log_event
    log_event("resolve", candidates=len(out), companies=len(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
