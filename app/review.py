"""One-page entity-resolution reviewer — confirm/reject Splink's duplicate-company candidates.

Reads data/staged/merge_candidates.json (from `make resolve`), shows one pair at a time with the
evidence (shared films, funding, SÍK), and writes decisions to data/curated/entity_merges.json —
which `make build` applies (the dropped name collapses into the canonical company, logged in alias).

Run:  make review     (streamlit run app/review.py in .venv)
"""
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "data" / "staged" / "merge_candidates.json"
MERGES = ROOT / "data" / "curated" / "entity_merges.json"

st.set_page_config(page_title="Entity resolution", layout="centered")


def load_merges():
    if MERGES.exists():
        d = json.loads(MERGES.read_text(encoding="utf-8"))
        d.setdefault("merges", [])
        d.setdefault("rejected", [])
        return d
    return {"_about": "Human-confirmed entity merges, applied by compile.py. 'drop' norms collapse into 'keep'.",
            "merges": [], "rejected": []}


def save_merges(d):
    MERGES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def decided_set(d):
    s = set()
    for m in d["merges"]:
        for drop in m.get("drop", []):
            s.add(frozenset((m["keep"], drop)))
    for a, b in d["rejected"]:
        s.add(frozenset((a, b)))
    return s


cands = json.loads(CAND.read_text(encoding="utf-8")) if CAND.exists() else []
merges = load_merges()
decided = decided_set(merges)
skipped = st.session_state.setdefault("skipped", set())
todo = [c for c in cands
        if frozenset((c["keep_norm"], c["drop_norm"])) not in decided
        and frozenset((c["keep_norm"], c["drop_norm"])) not in skipped]

st.title("🔗 Entity resolution — company duplicates")
if not CAND.exists():
    st.warning("No candidates yet. Run `make resolve` first.")
    st.stop()
done = len(cands) - len(todo)
st.progress(done / len(cands) if cands else 1.0,
            text=f"{done}/{len(cands)} reviewed · {len(merges['merges'])} merged · {len(merges['rejected'])} kept-separate")
if not todo:
    st.success("All candidate pairs reviewed 🎉  Run `make build` to apply the merges.")
    st.stop()

c = todo[0]
st.caption(f"Splink match probability: **{c['score']:.3f}**  ·  shared films: **{c['shared_films']}**")
swap = st.toggle("Keep the right-hand one as canonical instead", value=False)
left, right = (c, c)  # display values are symmetric; canonical chosen by swap
keep_name, keep_norm = (c["drop_name"], c["drop_norm"]) if swap else (c["keep_name"], c["keep_norm"])
drop_name, drop_norm = (c["keep_name"], c["keep_norm"]) if swap else (c["drop_name"], c["drop_norm"])

a, b = st.columns(2)
with a:
    st.subheader("✅ Keep" if not swap else "drop →")
    st.markdown(f"**{c['keep_name']}**")
    st.caption(f"films: {c['keep_films']} · funding: {c['keep_isk']:,} kr · SÍK: {'yes' if c['keep_sik'] else 'no'}")
with b:
    st.subheader("drop →" if not swap else "✅ Keep")
    st.markdown(f"**{c['drop_name']}**")
    st.caption(f"films: {c['drop_films']} · funding: {c['drop_isk']:,} kr")

st.divider()
b1, b2, b3 = st.columns(3)
if b1.button("✅ Same — merge", use_container_width=True, type="primary"):
    merges["merges"].append({"keep": keep_norm, "drop": [drop_norm], "drop_name": drop_name,
                             "keep_name": keep_name, "score": c["score"], "reason": "manual review"})
    save_merges(merges)
    st.rerun()
if b2.button("❌ Different — keep separate", use_container_width=True):
    merges["rejected"].append([c["keep_norm"], c["drop_norm"]])
    save_merges(merges)
    st.rerun()
if b3.button("⏭ Skip for now", use_container_width=True):
    skipped.add(frozenset((c["keep_norm"], c["drop_norm"])))
    st.rerun()

with st.expander("remaining queue (next 15)"):
    for x in todo[1:16]:
        st.text(f"{x['score']:.3f}  {x['keep_name'][:30]:30} ⇄ {x['drop_name'][:30]}  (shared {x['shared_films']})")
