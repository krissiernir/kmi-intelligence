"""Production browse index + profile page — makes `title` (films + series) a first-class clickable
entity, like the person/company profiles. Native clickable browse + plotly funding timeline.

render(st, db_path, query_params): shows the profile if ?title_id= is set, else the browse index.
STAGED — review + test before deploy. Schema per compile.py.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import plotly.express as px

FAMILY_IS = {"handrit": "Handrit", "throun": "Þróun", "framleidsla": "Framleiðsla",
             "eftirvinnsla": "Eftirvinnsla", "endurgreidsla": "Endurgreiðsla", "annad": "Aðrir"}
FAMILY_ORDER = {"handrit": 0, "throun": 1, "framleidsla": 2, "eftirvinnsla": 3, "endurgreidsla": 4, "annad": 5}
KIND_IS = {"film": "Kvikmynd", "series": "Þáttaröð", "documentary": "Heimildamynd", "short": "Stuttmynd"}
XREF_IS = {"matched": "Með úthlutun", "likely_unfunded": "Líklega óstyrkt", "ledger_gap": "Utan skrár"}


def _q(db_path, sql, params=()):
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:   # read-only
        return pd.read_sql_query(sql, c, params=params)


def _isk(n):
    return "—" if n is None or pd.isna(n) else f"{int(n):,}".replace(",", ".") + " kr."


def render(st, db_path, qp):
    tid = qp.get("title_id")
    if tid:
        _profile(st, db_path, qp, int(tid))
    else:
        _browse(st, db_path, qp)


# ───────────────────────── Browse index ─────────────────────────
def _browse(st, db_path, qp):
    st.title("Framleiðslur")
    st.caption("Kvikmyndir og þáttaraðir — leitaðu, smelltu til að sjá allt um verkið.")
    df = _q(db_path, "SELECT id, title, year, kind, director, kmi_funded, kmi_total_isk, xref_status FROM title")
    if df.empty:
        st.warning("Engin verk — keyrðu `make kvik && make wiki-films && make build`.")
        return
    c1, c2, c3 = st.columns(3)
    kinds = ["Allt"] + sorted(df["kind"].dropna().unique())
    kind = c1.selectbox("Tegund", kinds, format_func=lambda k: KIND_IS.get(k, k))
    search = c2.text_input("Leita í titli")
    funded = c3.selectbox("Fjármögnun", ["Allt", "Styrkt", "Óstyrkt"])

    f = df.copy()
    if kind != "Allt":
        f = f[f["kind"] == kind]
    if search:
        f = f[f["title"].fillna("").str.contains(search, case=False)]
    if funded == "Styrkt":
        f = f[f["kmi_funded"] == 1]
    elif funded == "Óstyrkt":
        f = f[f["kmi_funded"] == 0]

    show = f[["title", "year", "kind", "director", "kmi_total_isk", "xref_status"]].copy()
    show["kind"] = show["kind"].map(lambda k: KIND_IS.get(k, k))
    show["xref_status"] = show["xref_status"].map(lambda s: XREF_IS.get(s, s))
    show.columns = ["Titill", "Ár", "Tegund", "Leikstjóri", "KMÍ alls", "Staða"]
    st.caption(f"{len(show)} verk")

    # native clickable selection (Streamlit >= 1.35)
    try:
        ev = st.dataframe(show.sort_values("Ár", ascending=False), use_container_width=True,
                          hide_index=True, on_select="rerun", selection_mode="single-row")
        rows = ev.selection.rows if ev and ev.selection else []
        if rows:
            picked_idx = f.sort_values("year", ascending=False).iloc[rows[0]]["id"]
            qp["title_id"] = str(int(picked_idx))
            st.rerun()
    except TypeError:   # older Streamlit without on_select — fall back to a selectbox
        st.dataframe(show.sort_values("Ár", ascending=False), use_container_width=True, hide_index=True)
        pick = st.selectbox("Opna verk", f["title"], index=None, placeholder="Veldu verk…")
        if pick:
            qp["title_id"] = str(int(f[f["title"] == pick]["id"].iloc[0]))
            st.rerun()


# ───────────────────────── Profile page ─────────────────────────
def _profile(st, db_path, qp, tid, flagging=None):
    t = _q(db_path, "SELECT * FROM title WHERE id=?", (tid,))
    if t.empty:
        st.error("Verk fannst ekki.")
        if st.button("← Til baka"): qp.pop("title_id", None); st.rerun()
        return
    t = t.iloc[0]
    if st.button("← Til baka í lista"):
        qp.pop("title_id", None); st.rerun()

    st.title(t["title"])
    st.caption(f"{KIND_IS.get(t['kind'], t['kind'])} · {int(t['year']) if pd.notna(t['year']) else '—'}"
               f"{' · ' + t['director'] if t['director'] else ''}")

    m = st.columns(4)
    m[0].metric("KMÍ alls", _isk(t["kmi_total_isk"]))
    m[1].metric("Úthlutanir", int(t["kmi_alloc_count"] or 0))
    m[2].metric("Staða", XREF_IS.get(t["xref_status"], t["xref_status"] or "—"))
    if pd.notna(t["imdb_rating"]):
        m[3].metric("IMDb", f"{t['imdb_rating']} ({int(t['imdb_votes'] or 0)})")

    # ── funding timeline: who got funded, in what order ──
    aw = _q(db_path, """SELECT a.year, a.family, a.amount_isk, a.format_track, a.company, a.writer, a.producer
                        FROM award aw JOIN allocations a ON a.id = aw.allocation_id
                        WHERE aw.title_id = ?""", (tid,))
    if not aw.empty:
        aw["stig"] = aw["family"].map(lambda f: FAMILY_ORDER.get(f, 9))
        aw = aw.sort_values(["year", "stig"])
        aw["Flokkur"] = aw["family"].map(lambda f: FAMILY_IS.get(f, f))
        aw["Móttakandi"] = aw["company"].fillna(aw["writer"]).fillna(aw["producer"]).fillna("—")
        st.subheader("Fjármögnun — í hvaða röð styrkt var")
        tl = aw[["year", "Flokkur", "amount_isk", "Móttakandi"]].copy()
        tl.columns = ["Ár", "Flokkur", "Upphæð", "Móttakandi"]
        st.dataframe(tl, use_container_width=True, hide_index=True)
        try:
            fig = px.bar(aw, x="amount_isk", y="Flokkur", color="Flokkur", orientation="h",
                         hover_data=["year", "Móttakandi"], labels={"amount_isk": "Upphæð (kr.)"})
            fig.update_layout(showlegend=False, title="Styrkir eftir stigi")
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass
    else:
        st.info("Engin úthlutun fannst í skránni (2021–2024). "
                + (XREF_IS.get(t["xref_status"], "") or ""))

    # ── who worked on it ──
    cr = _q(db_path, """SELECT p.id pid, p.display_name nafn, tc.role hlutverk, tc.job starf
                        FROM title_credit tc JOIN person p ON p.id = tc.person_id
                        WHERE tc.title_id = ? ORDER BY tc.role, p.display_name""", (tid,))
    if not cr.empty:
        st.subheader("Aðstandendur")
        for role in cr["hlutverk"].unique():
            names = ", ".join(cr[cr["hlutverk"] == role]["nafn"])
            st.write(f"**{role}:** {names}")

    co = _q(db_path, """SELECT c.name nafn, tc.role hlutverk FROM title_company tc
                        JOIN company c ON c.id = tc.company_id WHERE tc.title_id = ?""", (tid,))
    if not co.empty:
        st.subheader("Fyrirtæki")
        st.dataframe(co.rename(columns={"nafn": "Fyrirtæki", "hlutverk": "Hlutverk"}),
                     use_container_width=True, hide_index=True)

    # ── all data + provenance ──
    with st.expander("Öll gögn + heimildir"):
        st.caption(f"Heimild: {t['source']} · áreiðanleiki: {t['confidence']} · samsvörun: {t['match_confidence']}")
        if t["url"]:
            st.write(f"[Tengill]({t['url']})")
        if t["imdb_tconst"]:
            st.write(f"[IMDb](https://www.imdb.com/title/{t['imdb_tconst']}/)")
        st.json({k: (json.loads(v) if isinstance(v, str) and k.endswith("_json") and v else v)
                 for k, v in t.items() if pd.notna(v)}, expanded=False)

    # ── flag control (4th trust layer) ──
    if flagging is not None:
        flagging.flag_button(st, "title", tid, t["title"])
