"""KMÍ Intelligence — producer dashboard over the v2 knowledge base (build/kmi.db).

Run:  make run        (uses .venv/bin/streamlit)
  or  .venv/bin/streamlit run app/streamlit_app.py

Read-only over build/kmi.db. The semantic-search page shells out to the local RAG
backend in .venv-rag (falls back to keyword search if that venv is absent).
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "build" / "kmi.db"
RAG_PY = ROOT / ".venv-rag" / "bin" / "python"
QUEUE = ROOT / "logs" / "review_queue.jsonl"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make app/ modules importable
import flagging  # noqa: E402  🚩 review queue (writes its own jsonl, never kmi.db)
import labels_is as L  # noqa: E402  Icelandic labels
import production_profile  # noqa: E402  Framleiðslur browse + profile
import viz  # noqa: E402  plotly cockpit charts

try:
    import ask_biomonsi  # needs anthropic + ANTHROPIC_API_KEY — optional
except Exception:
    ask_biomonsi = None

st.set_page_config(page_title="Bíómonsi — KMÍ Intelligence", layout="wide")

if not DB.exists():
    st.error("build/kmi.db not found. Run `make build` first (and `make parse` for the ledger).")
    st.stop()


def _fold(s) -> str:
    """Lowercase + strip diacritics so 'Ólaf' matches 'Olaf' (þ/ð/æ/ö kept — distinct letters)."""
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "").lower())
                   if not unicodedata.combining(ch))


@st.cache_data
def _q_cached(sql: str, params: tuple, mtime: float) -> pd.DataFrame:
    with sqlite3.connect(DB) as c:
        c.create_function("fold", 1, _fold, deterministic=True)  # diacritic-insensitive search
        return pd.read_sql_query(sql, c, params=params)


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    # key the cache on the DB's mtime so a nightly rebuild / `make build` actually shows
    return _q_cached(sql, tuple(params), DB.stat().st_mtime)


def isk(n) -> str:
    return "—" if n is None or pd.isna(n) else f"{int(n):,}".replace(",", ".") + " kr."


FAMILY_LABEL = {
    "handrit": "Handrit (screenwriting)", "throun": "Þróun (development)",
    "framleidsla": "Framleiðsla (production)", "eftirvinnsla": "Eftirvinnsla (post)",
    "endurgreidsla": "Endurgreiðsla (rebate)", "annad": "Aðrir (other)",
}

st.sidebar.title("🎬 Bíómonsi")
# routing keys stay stable (English); only the DISPLAY is Icelandic (relabel = low-risk)
PAGE_LABELS = {
    "📊 Overview": "📊 Yfirlit",
    "🎬 Grant browser": "🎬 Skoða styrki",
    "📋 Document matrix": "📋 Skjalakröfur",
    "💰 Funding explorer": "💰 Úthlutanir",
    "🎞️ Productions ↔ funding": "🎞️ Framleiðslur",
    "🧑‍🎬 People & companies": "🧑‍🎬 Fólk og fyrirtæki",
    "📐 Amounts & rebate": "📐 Upphæðir og endurgreiðsla",
    "🔎 Semantic search": "🔎 Merkingarleit",
    "💬 Ask Bíómonsi": "💬 Spyrja Bíómonsi",
}
page = st.sidebar.radio("Síða", list(PAGE_LABELS), format_func=lambda p: PAGE_LABELS[p])
st.sidebar.caption(L.t("sidebar_caption"))
_fsum = flagging.summary(QUEUE)
if _fsum["open"]:
    st.sidebar.caption(f"🚩 {_fsum['open']} opin merki til skoðunar")


# ───────────────────────── Overview ─────────────────────────
if page == "📊 Overview":
    st.title("KMÍ Intelligence — producer dashboard")
    st.caption("Source-traceable knowledge base of what KMÍ offers and has funded (2021–2024).")
    n_streams = q("SELECT COUNT(*) n FROM grant_streams")["n"][0]
    n_docs = q("SELECT COUNT(*) n FROM stream_documents")["n"][0]
    n_alloc = q("SELECT COUNT(*) n FROM allocations")["n"][0]
    total = q("SELECT SUM(amount_isk) s FROM allocations WHERE amount_isk IS NOT NULL")["s"][0]
    c = st.columns(4)
    c[0].metric("Grant streams (gáttir)", n_streams)
    c[1].metric("Document requirements", n_docs)
    c[2].metric("Awards 2021–2024", n_alloc)
    c[3].metric("Total disbursed", isk(total))

    st.subheader("Úthlutað eftir árum")
    by_year = q("SELECT year, SUM(amount_isk) total FROM allocations WHERE amount_isk IS NOT NULL GROUP BY year ORDER BY year")
    st.bar_chart(by_year, x="year", y="total")

    # ── viz cockpit (plotly): concentration + flow + lane trends ──
    alloc = q("SELECT year, family, amount_isk, format_track, company FROM allocations")
    viz.treemap(st, alloc)
    cL, cR = st.columns(2)
    with cL:
        viz.trends(st, alloc)
    with cR:
        viz.sankey(st, alloc, backend=viz.backend_picker(st, "sankey", key="ov_sankey"))

    st.info("**Amounts:** the *application maximum* (per gátta) and the *disbursement parts* "
            "(how awards are paid out) are different numbers — see the **Amounts & rebate** page. "
            "Most catalog facts are `needs_verification`; ledger figures come from the official úthlutanir PDFs.")


# ───────────────────────── Grant browser ─────────────────────────
elif page == "🎬 Grant browser":
    st.title("Grant browser")
    fams = q("SELECT id, name_is FROM grant_families ORDER BY id")
    fam = st.selectbox("Family", fams["id"], format_func=lambda i: FAMILY_LABEL.get(i, i))
    streams = q("SELECT * FROM grant_streams WHERE family=? ORDER BY stage, level", (fam,))
    if streams.empty:
        st.warning("No streams in this family yet.")
        st.stop()
    sid = st.selectbox("Stream (gátta)", streams["id"],
                       format_func=lambda i: streams.loc[streams["id"] == i, "name_is"].iloc[0])
    s = streams[streams["id"] == sid].iloc[0]

    def _has(v):  # NULLs read back from pandas as NaN (a float) — NaN is truthy, so guard explicitly
        return pd.notna(v) and str(v).strip() not in ("", "None")

    st.subheader(s["name_is"])
    if _has(s["name_en"]):
        st.caption(str(s["name_en"]))
    c = st.columns(3)
    c[0].metric("Application max", isk(s["max_amount_isk"]) if _has(s["max_amount_isk"]) else "scope-dependent")
    c[1].metric("Stage", s["stage"])
    c[2].metric("Gátta ID", s["gatta_id"] or "—")
    if _has(s["purpose"]):
        st.write("**Markmið:** " + str(s["purpose"]))
    if _has(s["amount_basis"]):
        st.caption("💡 " + str(s["amount_basis"]))
    if _has(s["payment_split"]):
        st.write("**Greiðsluskipting:** " + str(s["payment_split"]))
    if _has(s["portal_url"]):
        st.write(f"**Apply:** [{s['portal_url']}]({s['portal_url']})")
    rules = json.loads(s["rules_json"] or "{}")
    if rules:
        st.write("**Skilyrði / rules:**")
        for k_, v_ in rules.items():
            st.write(f"- *{k_}*: {v_}")

    st.markdown("#### Documents (fylgigögn)")
    docs = q("SELECT requirement_level, document_text FROM stream_documents WHERE stream_id=? ORDER BY rowid", (sid,))
    for lvl in ["required", "newcomer", "recommended", "strategic", "optional"]:
        d = docs[docs["requirement_level"] == lvl]
        if not d.empty:
            st.write(f"**{lvl.capitalize()}:**")
            for t in d["document_text"]:
                st.write(f"- {t}")
    st.caption(f"Confidence: `{s['confidence']}` · sources: {s['sources_json']}")


# ───────────────────────── Document matrix ─────────────────────────
elif page == "📋 Document matrix":
    st.title("Document matrix")
    df = q("""SELECT gs.family, gs.name_is AS stream, sd.requirement_level, sd.document_text
              FROM stream_documents sd JOIN grant_streams gs ON gs.id = sd.stream_id""")
    c1, c2 = st.columns(2)
    fam = c1.selectbox("Family", ["All"] + sorted(df["family"].unique()))
    lvl = c2.selectbox("Requirement", ["All"] + sorted(df["requirement_level"].unique()))
    if fam != "All":
        df = df[df["family"] == fam]
    if lvl != "All":
        df = df[df["requirement_level"] == lvl]
    st.caption(f"{len(df)} requirements")
    st.dataframe(df, use_container_width=True, hide_index=True)


# ───────────────────────── Funding explorer ─────────────────────────
elif page == "💰 Funding explorer":
    st.title("Funding explorer — úthlutanir 2021–2024")
    df = q("SELECT * FROM allocations")
    c1, c2, c3 = st.columns(3)
    years = sorted(df["year"].dropna().astype(int).unique())
    ysel = c1.multiselect("Years", years, default=years)
    fams = sorted(df["family"].dropna().unique())
    fsel = c2.multiselect("Family", fams, default=fams)
    comp = c3.text_input("Company contains", "")

    f = df[df["year"].isin(ysel) & df["family"].isin(fsel)]
    if comp:
        f = f[f["company"].fillna("").str.contains(comp, case=False)]

    paid = f[f["amount_isk"].notna()]
    m = st.columns(3)
    m[0].metric("Awards", len(f))
    m[1].metric("Total grant", isk(paid["amount_isk"].sum()))
    m[2].metric("Median grant", isk(paid["amount_isk"].median()) if not paid.empty else "—")

    st.subheader("By family")
    st.bar_chart(paid.groupby("family")["amount_isk"].sum())
    st.subheader("Top companies")
    top = paid.groupby("company")["amount_isk"].sum().sort_values(ascending=False).head(15)
    st.bar_chart(top)

    st.subheader("Awards")
    st.dataframe(
        f[["year", "project_title", "family", "company", "director", "amount_isk", "commitment_isk", "confidence"]]
        .sort_values("amount_isk", ascending=False),
        use_container_width=True, hide_index=True,
    )


# ───────────────────────── People & companies ─────────────────────────
elif page == "🧑‍🎬 People & companies":
    st.title("People & companies")
    st.caption("Entity spine built from the úthlutanir ledger + production catalogs + the SÍK "
               "registry. Name-based resolution; same-name people may merge.")
    kind = st.radio("Look up a", ["Person", "Company"], horizontal=True)
    if kind == "Person":
        name = st.text_input("Person name", "Olaf de Fleur")
        matches = q("SELECT id, display_name, primary_roles, credit_count, imdb_nconst, source FROM person "
                    "WHERE fold(display_name) LIKE fold(?) ORDER BY credit_count DESC LIMIT 25", (f"%{name}%",))
        if matches.empty:
            st.info("No match.")
        else:
            if len(matches) > 1:
                st.caption(f"⚠ {len(matches)} matches — same-name rows may be the *same person* not yet "
                           "merged (run `make resolve`/`make review`). Pick one:")
                labels = [f"{r.display_name} — {r.credit_count} credits"
                          + (f" · IMDb {r.imdb_nconst}" if r.imdb_nconst else "")
                          + f" · {r.source} · #{r.id}" for r in matches.itertuples()]
                p = matches.iloc[st.selectbox("Match", range(len(labels)), format_func=lambda i: labels[i])]
            else:
                p = matches.iloc[0]
            st.subheader(f"{p['display_name']}")
            st.caption(f"Roles: {p['primary_roles']} · {p['credit_count']} credits"
                       + (f" · IMDb {p['imdb_nconst']}" if p['imdb_nconst'] else "") + f" · source {p['source']}")
            flagging.flag_button(st, "person", int(p["id"]), p["display_name"], queue_path=QUEUE)
            st.markdown("**Filmography**")
            st.dataframe(q("""SELECT t.year, t.title, tc.role, t.kind, t.kmi_funded
                              FROM title_credit tc JOIN title t ON t.id=tc.title_id
                              WHERE tc.person_id=? ORDER BY t.year DESC, t.title""", (int(p["id"]),)),
                         use_container_width=True, hide_index=True)
            st.markdown("**Frequent collaborators**")
            st.dataframe(q("""SELECT p2.display_name AS collaborator, COUNT(*) AS together
                              FROM title_credit c1 JOIN title_credit c2 ON c1.title_id=c2.title_id AND c1.person_id<>c2.person_id
                              JOIN person p2 ON p2.id=c2.person_id WHERE c1.person_id=?
                              GROUP BY c2.person_id ORDER BY together DESC LIMIT 10""", (int(p["id"]),)),
                         use_container_width=True, hide_index=True)
    else:
        name = st.text_input("Company name", "Glassriver")
        cos = q("SELECT * FROM company WHERE fold(name) LIKE fold(?) ORDER BY kmi_total_isk DESC LIMIT 25", (f"%{name}%",))
        if cos.empty:
            st.info("No match.")
        else:
            if len(cos) > 1:
                labels = [f"{r.name} — {r.kmi_grants_count or 0} grants · {r.type or '?'} · #{r.id}" for r in cos.itertuples()]
                co = cos.iloc[st.selectbox("Match", range(len(labels)), format_func=lambda i: labels[i])]
            else:
                co = cos.iloc[0]
            st.subheader(co["name"])
            st.caption(f"{'SÍK member · ' if co['is_sik_member'] else ''}{co['website'] or ''}  ·  "
                       f"{co['kmi_grants_count']} grants / {isk(co['kmi_total_isk'])}")
            flagging.flag_button(st, "company", int(co["id"]), co["name"], queue_path=QUEUE)
            raws = q("SELECT raw_string FROM alias WHERE entity_type='company' AND entity_id=? AND status='resolved'", (int(co["id"]),))
            if not raws.empty:
                ph = ",".join("?" * len(raws))
                st.markdown("**Funded projects**")
                st.dataframe(q(f"""SELECT DISTINCT year, project_title, amount_isk, family FROM allocations
                                   WHERE company IN ({ph}) AND amount_isk IS NOT NULL ORDER BY year DESC, amount_isk DESC""",
                               tuple(raws["raw_string"])), use_container_width=True, hide_index=True)
            mc = q("SELECT DISTINCT raw_string FROM alias WHERE entity_type='company' AND entity_id=? AND status='unresolved'", (int(co["id"]),))
            if not mc.empty:
                st.markdown("**Merge candidates (parked for review)**")
                st.write(", ".join(mc["raw_string"]))

# ───────────────────────── Amounts & rebate ─────────────────────────
elif page == "📐 Amounts & rebate":
    st.title("Amounts & rebate")
    st.info("**Application maximum** (what you can request, from the live styrkir pages) is on each "
            "grant stream. **Disbursement parts** below (how awards were paid out by progress) come "
            "from the úthlutanir PDFs — they are *different numbers*.")

    st.subheader("Application maxima (per gátta)")
    st.dataframe(q("""SELECT gatta_id, name_is, family,
                        CASE WHEN max_amount_isk IS NULL THEN 'scope-dependent' ELSE max_amount_isk END AS max_isk,
                        amount_basis FROM grant_streams
                      WHERE family IN ('handrit','throun','eftirvinnsla') ORDER BY format_track, stage, level"""),
                 use_container_width=True, hide_index=True)

    st.subheader("Disbursement history (verbatim from PDFs)")
    st.dataframe(q("SELECT family, format_track, year, structure, parts_json, total_isk, source_line FROM grant_amounts ORDER BY family, format_track, year"),
                 use_container_width=True, hide_index=True)

    st.subheader("Endurgreiðsla (rebate)")
    r = q("SELECT * FROM rebate").iloc[0]
    st.write(f"- **{r['general_pct']}%** general — {r['general_basis']}")
    st.write(f"- **{r['enhanced_pct']}%** enhanced — {r['enhanced_conditions']}")
    st.caption(r["regla_18_manuda"])

    st.subheader("Application & delivery process")
    st.dataframe(q("SELECT ord, name_is, condition, deadline_months FROM process_stages ORDER BY ord"),
                 use_container_width=True, hide_index=True)


# ───────────────────────── Productions ↔ funding ─────────────────────────
elif page == "🎞️ Productions ↔ funding":
    # richer browse + clickable profile (deep-links via ?title_id=); flagging passed through
    production_profile.render(st, DB, st.query_params)

# ───────────────────────── Semantic search ─────────────────────────
elif page == "🔎 Semantic search":
    st.title("Semantic search (RAG)")
    query = st.text_input("Ask in Icelandic or English", "þróunarstyrkur fyrir heimildamynd")
    k = st.slider("Results", 3, 15, 5)
    if st.button("Search") and query:
        if RAG_PY.exists():
            with st.spinner("Embedding query with multilingual-e5…"):
                out = subprocess.run(
                    [str(RAG_PY), "-m", "kmi_intelligence.rag", "search", query,
                     "--backend", "local", "-k", str(k), "--json"],
                    cwd=ROOT, env={**os.environ, "PYTHONPATH": "src"},
                    capture_output=True, text=True, timeout=180,
                )
            lines = [l for l in out.stdout.splitlines() if l.strip().startswith("[")]
            if lines:
                res = pd.DataFrame(json.loads(lines[-1]))
                st.dataframe(res[["score", "type", "text"]], use_container_width=True, hide_index=True)
            else:
                st.error("Search failed.")
                st.code(out.stderr[-1000:] or out.stdout[-1000:])
        else:
            st.warning("Local RAG venv (.venv-rag) not found — run `make embed-setup && make embed`. "
                       "Falling back to keyword search over chunks.")
            chunks = ROOT / "build" / "embeddings" / "chunks.jsonl"
            if chunks.exists():
                rows = [json.loads(x) for x in chunks.read_text(encoding="utf-8").splitlines()]
                hits = [r for r in rows if query.lower() in r["text"].lower()][:k]
                st.dataframe(pd.DataFrame([{"type": r["metadata"].get("type"), "text": r["text"]} for r in hits]),
                             use_container_width=True, hide_index=True)


# ───────────────────────── Ask Bíómonsi (conversational text-to-SQL) ─────────────────────────
elif page == "💬 Ask Bíómonsi":
    if ask_biomonsi is None:
        st.title("Spyrja Bíómonsi")
        st.warning("`anthropic` pakkann vantar — `pip install anthropic` og settu `ANTHROPIC_API_KEY` "
                   "í umhverfið til að virkja samtals-fyrirspurnir (read-only text-to-SQL).")
    else:
        ask_biomonsi.render(st, str(DB))
