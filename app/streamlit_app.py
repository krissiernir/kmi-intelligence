from __future__ import annotations

import sqlite3
import pandas as pd
import streamlit as st

from src.kmi_intelligence.db import get_connection, create_schema
from src.kmi_intelligence.seed import load_seed_data
from src.kmi_intelligence.readiness import compute_readiness, stage_mismatch_flags
from src.kmi_intelligence.analysis import allocation_summary
from src.kmi_intelligence.prompt_builder import build_prompt


@st.cache_resource
def init_db() -> sqlite3.Connection:
    conn = get_connection()
    create_schema(conn)
    return conn


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", conn)


st.set_page_config(page_title="KMI Intelligence MVP", layout="wide")
st.title("KMÍ Intelligence — Producer Dashboard (Local MVP)")

conn = init_db()

with st.sidebar:
    st.header("Navigation")
    page = st.radio("Page", [
        "Home", "Grant Browser", "Document Matrix", "Allocation Explorer", "Project Readiness Checker", "AI Brief Builder"
    ])
    if st.button("Reload seed data"):
        load_seed_data(conn)
        st.success("Seed data reloaded.")

if page == "Home":
    st.write("Local-first grant intelligence tool for Icelandic film producers. This MVP uses sample data and heuristics.")
    cols = st.columns(4)
    cols[0].metric("Grants", len(read_table(conn, "grants")))
    cols[1].metric("Documents", len(read_table(conn, "documents")))
    cols[2].metric("Allocations", len(read_table(conn, "allocations")))
    cols[3].metric("Projects", len(read_table(conn, "projects")))

elif page == "Grant Browser":
    grants = read_table(conn, "grants")
    selected_id = st.selectbox("Select grant", grants["id"], format_func=lambda i: grants.loc[grants["id"] == i, "name_is"].iloc[0])
    g = grants[grants["id"] == selected_id].iloc[0]
    st.subheader(g["name_is"])
    st.write({k: g[k] for k in ["purpose", "category", "best_stage", "eligibility_summary", "last_checked", "confidence"]})

    req = pd.read_sql_query(
        """SELECT gdr.requirement_level, d.name_is FROM grant_document_requirements gdr
           JOIN documents d ON d.id = gdr.document_id WHERE gdr.grant_id = ?""", conn, params=(selected_id,)
    )
    st.markdown("### Documents")
    st.dataframe(req)

    crit = pd.read_sql_query(
        """SELECT c.name, c.axis, c.description FROM grant_criteria gc
           JOIN criteria c ON c.id = gc.criterion_id WHERE gc.grant_id = ?""", conn, params=(selected_id,)
    )
    st.markdown("### Criteria")
    st.dataframe(crit)

elif page == "Document Matrix":
    q = """SELECT g.category, g.name_is as grant_name, d.name_is as document_name, gdr.requirement_level
           FROM grant_document_requirements gdr
           JOIN grants g ON g.id = gdr.grant_id
           JOIN documents d ON d.id = gdr.document_id"""
    df = pd.read_sql_query(q, conn)
    c1, c2 = st.columns(2)
    cat = c1.selectbox("Category", ["All"] + sorted(df["category"].dropna().unique().tolist()))
    lvl = c2.selectbox("Requirement level", ["All", "required", "recommended", "strategic", "conditional", "not_applicable", "unknown"])
    if cat != "All":
        df = df[df["category"] == cat]
    if lvl != "All":
        df = df[df["requirement_level"] == lvl]
    st.dataframe(df)

elif page == "Allocation Explorer":
    df = read_table(conn, "allocations")
    c1, c2, c3, c4 = st.columns(4)
    years = sorted(df["year"].dropna().astype(int).unique().tolist())
    selected_years = c1.multiselect("Years", years, default=years)
    cats = sorted(df["grant_category_raw"].dropna().unique().tolist())
    selected_cats = c2.multiselect("Categories", cats, default=cats)
    companies = sorted(df["company_name"].dropna().unique().tolist())
    selected_companies = c3.multiselect("Companies", companies, default=companies)
    min_amt, max_amt = int(df["amount_isk"].min()), int(df["amount_isk"].max())
    amt_range = c4.slider("Amount range", min_amt, max_amt, (min_amt, max_amt))

    filt = df[df["year"].isin(selected_years) & df["grant_category_raw"].isin(selected_cats) & df["company_name"].isin(selected_companies)]
    filt = filt[(filt["amount_isk"] >= amt_range[0]) & (filt["amount_isk"] <= amt_range[1])]
    st.dataframe(filt)

    summary = allocation_summary(filt)
    st.metric("Total amount", f"{summary['total']:,} ISK")
    st.metric("Average amount", f"{summary['avg']:,.0f} ISK")
    st.metric("Median amount", f"{summary['median']:,.0f} ISK")
    st.write("Count by grant category")
    st.dataframe(filt.groupby("grant_category_raw").size().rename("count"))
    st.write("Top companies by total amount")
    st.dataframe(summary["top_companies"].rename("total_isk"))

elif page == "Project Readiness Checker":
    projects = read_table(conn, "projects")
    grants = read_table(conn, "grants")
    pid = st.selectbox("Project", projects["id"], format_func=lambda i: projects.loc[projects["id"] == i, "title"].iloc[0])
    gid = st.selectbox("Target grant", grants["id"], format_func=lambda i: grants.loc[grants["id"] == i, "name_is"].iloc[0])

    req = pd.read_sql_query(
        """SELECT gdr.document_id, gdr.requirement_level, d.name_is FROM grant_document_requirements gdr
           JOIN documents d ON d.id = gdr.document_id WHERE gdr.grant_id = ?""", conn, params=(gid,)
    )
    pdocs = pd.read_sql_query("SELECT * FROM project_documents WHERE project_id = ?", conn, params=(pid,))
    result = compute_readiness(req, pdocs)
    st.metric("Readiness score (heuristic)", f"{result['score']}%")
    st.caption("Heuristic only. Not an official KMÍ evaluation model.")

    st.write("Missing required", result["missing"]["required"])
    st.write("Missing recommended", result["missing"]["recommended"])
    st.write("Missing strategic", result["missing"]["strategic"])

    p = projects[projects["id"] == pid].iloc[0]
    g = grants[grants["id"] == gid].iloc[0]
    flags = stage_mismatch_flags(str(p["stage"]), str(g["best_stage"]))
    if flags:
        st.warning("\n".join(flags))

elif page == "AI Brief Builder":
    modes = ["Grant fit analysis", "Document checklist", "Brutal consultant review", "Application rewrite", "Allocation pattern analysis"]
    mode = st.selectbox("Prompt mode", modes)
    projects = read_table(conn, "projects")
    grants = read_table(conn, "grants")
    pid = st.selectbox("Project", projects["id"], format_func=lambda i: projects.loc[projects["id"] == i, "title"].iloc[0])
    gid = st.selectbox("Grant", grants["id"], format_func=lambda i: grants.loc[grants["id"] == i, "name_is"].iloc[0])

    req = pd.read_sql_query(
        """SELECT gdr.document_id, gdr.requirement_level, d.name_is FROM grant_document_requirements gdr
           JOIN documents d ON d.id = gdr.document_id WHERE gdr.grant_id = ?""", conn, params=(gid,)
    )
    pdocs = pd.read_sql_query("SELECT * FROM project_documents WHERE project_id = ?", conn, params=(pid,))
    readiness = compute_readiness(req, pdocs)

    docs = {
        "required": req[req["requirement_level"] == "required"]["name_is"].tolist(),
        "recommended": req[req["requirement_level"] == "recommended"]["name_is"].tolist(),
        "strategic": req[req["requirement_level"] == "strategic"]["name_is"].tolist(),
        "missing_required": readiness["missing"]["required"],
        "missing_recommended": readiness["missing"]["recommended"],
        "missing_strategic": readiness["missing"]["strategic"],
    }
    crit = pd.read_sql_query("""SELECT c.name, c.description FROM grant_criteria gc JOIN criteria c ON c.id = gc.criterion_id WHERE gc.grant_id = ?""", conn, params=(gid,))
    crit_lines = [f"{r['name']}: {r['description']}" for _, r in crit.iterrows()]
    alloc = read_table(conn, "allocations")
    alloc_note = f"Sample records: {len(alloc)}. Total ISK: {int(alloc['amount_isk'].sum()):,}."
    prompt = build_prompt(mode, projects[projects['id'] == pid].iloc[0].to_dict(), grants[grants['id'] == gid].iloc[0].to_dict(), docs, crit_lines, alloc_note)
    st.text_area("Copyable prompt", prompt, height=400)
