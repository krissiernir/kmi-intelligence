"""One-page entity-resolution reviewer — confirm/reject Splink's duplicate candidates (companies & people).

Reads data/staged/merge_candidates.json ({"company":[...], "person":[...]} from `make resolve`),
shows one pair at a time with evidence (shared films/titles, funding, IMDb nconst), and writes
decisions to data/curated/entity_merges.json ({company,person}.{merges,rejected}) — applied by
`make build` (the dropped name collapses into the canonical, logged in alias).

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
    d = json.loads(MERGES.read_text(encoding="utf-8")) if MERGES.exists() else {}
    if "merges" in d:  # migrate old flat (company-only) format
        d = {"company": {"merges": d.get("merges", []), "rejected": d.get("rejected", [])}}
    for e in ("company", "person"):
        d.setdefault(e, {"merges": [], "rejected": []})
    d.setdefault("_about", "Human-confirmed entity merges, applied by compile.py.")
    return d


def save_merges(d):
    MERGES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def decided(em):
    s = set()
    for m in em["merges"]:
        for drop in m.get("drop", []):
            s.add(frozenset((m["keep"], drop)))
    for a, b in em["rejected"]:
        s.add(frozenset((a, b)))
    return s


cands = json.loads(CAND.read_text(encoding="utf-8")) if CAND.exists() else {}
if isinstance(cands, list):  # migrate old flat format
    cands = {"company": cands}
merges = load_merges()

st.title("🔗 Entity resolution")
if not CAND.exists():
    st.warning("No candidates yet. Run `make resolve` (or `make resolve all`).")
    st.stop()

entity = st.radio("Resolve", ["company", "person"], horizontal=True,
                  format_func=lambda e: f"{e.title()}s ({len(cands.get(e, []))})")
items = cands.get(entity, [])
em = merges[entity]
done_set = decided(em)
skipped = st.session_state.setdefault(f"skip_{entity}", set())
todo = [c for c in items
        if frozenset((c["keep_norm"], c["drop_norm"])) not in done_set
        and frozenset((c["keep_norm"], c["drop_norm"])) not in skipped]

done = len(items) - len(todo)
st.progress(done / len(items) if items else 1.0,
            text=f"{done}/{len(items)} reviewed · {len(em['merges'])} merged · {len(em['rejected'])} kept-separate")
if not todo:
    st.success(f"All {entity} candidates reviewed 🎉  Run `make build` to apply.")
    st.stop()

c = todo[0]
work = "films" if entity == "company" else "titles"
st.caption(f"match probability **{c['score']:.3f}** · shared {work}: **{c['shared']}**"
           + (f" · method {c['method']}" if c.get("method") else ""))
swap = st.toggle("Keep the right-hand one instead", value=False)
keep_name, keep_norm = (c["drop_name"], c["drop_norm"]) if swap else (c["keep_name"], c["keep_norm"])
drop_name, drop_norm = (c["keep_name"], c["keep_norm"]) if swap else (c["drop_name"], c["drop_norm"])

a, b = st.columns(2)
for col, side, lbl in ((a, "keep", "✅ Keep" if not swap else "drop →"),
                       (b, "drop", "drop →" if not swap else "✅ Keep")):
    with col:
        st.subheader(lbl)
        st.markdown(f"**{c[side + '_name']}**")
        extra = f" · IMDb {c.get(side + '_nconst')}" if entity == "person" and c.get(side + "_nconst") else ""
        st.caption(f"{c[side + '_works']} {work}{extra}")

st.divider()
b1, b2, b3 = st.columns(3)
if b1.button("✅ Same — merge", use_container_width=True, type="primary"):
    em["merges"].append({"keep": keep_norm, "drop": [drop_norm], "keep_name": keep_name,
                         "drop_name": drop_name, "score": c["score"], "reason": "manual review"})
    save_merges(merges)
    st.rerun()
if b2.button("❌ Different — keep separate", use_container_width=True):
    em["rejected"].append([c["keep_norm"], c["drop_norm"]])
    save_merges(merges)
    st.rerun()
if b3.button("⏭ Skip", use_container_width=True):
    skipped.add(frozenset((c["keep_norm"], c["drop_norm"])))
    st.rerun()

with st.expander(f"remaining {entity} queue (next 15)"):
    for x in todo[1:16]:
        st.text(f"{x['score']:.2f}  {x['keep_name'][:28]:28} ⇄ {x['drop_name'][:28]}  (shared {x['shared']})")
