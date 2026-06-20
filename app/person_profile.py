"""Person dossier — a meeting-ready, stat-rich profile for one person.

Answers the questions a producer would want walking into a room: how many projects, what was
their first film, how many KMÍ grants were they approved for (and in what), who do they work with
most, how active are they. Built from data we already have — title_credit (catalog work), the IMDb
careers fold (real career first-feature), and allocations 2015–24 (KMÍ funding approvals as
writer/director/producer). Designed to grow: the NGO corpus will add board/membership context.

compute(db_path, pid) -> dict   (pure stats, also used by the markdown export)
render(st, db_path, pid)        (the Streamlit dossier)
to_markdown(stats) -> str       (a clean text version to paste into a doc / pull up to a meeting)

Schema per compile.py. Read-only.
"""
from __future__ import annotations

import re
import sqlite3

import pandas as pd

FAMILY_IS = {"handrit": "Handritsstyrkur", "throun": "Þróunarstyrkur", "framleidsla": "Framleiðslustyrkur",
             "eftirvinnsla": "Eftirvinnsla", "endurgreidsla": "Endurgreiðsla", "annad": "Annað"}


def _ro(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-záéíóúýþæöð ]", " ", (s or "").lower())).strip()


def _names(s: str):
    """Split a multi-name allocation field ('X og Y', 'A, B', 'Co/ Producer') into normalized names."""
    return [n for n in (_norm(x) for x in re.split(r"\s+og\s+|,|/|&", s or "")) if len(n) > 4]


def _isk(n) -> str:
    return "—" if not n else f"{int(n):,}".replace(",", ".") + " kr."


def _person_norms(c, pid: int) -> set:
    """Every normalized name this person is known by (display + confirmed aliases) — for funding match."""
    norms = set()
    row = c.execute("SELECT display_name, name_norm FROM person WHERE id=?", (pid,)).fetchone()
    if row:
        norms.add(_norm(row["display_name"]))
        if row["name_norm"]:
            norms.add(row["name_norm"])
    for a in c.execute("SELECT raw_norm FROM alias WHERE entity_type='person' AND entity_id=?", (pid,)):
        if a["raw_norm"]:
            norms.add(a["raw_norm"])
    return {n for n in norms if len(n) > 4}


def compute(db_path, pid: int) -> dict:
    c = _ro(db_path)
    p = c.execute("SELECT * FROM person WHERE id=?", (pid,)).fetchone()
    if not p:
        return {}
    out = {"id": pid, "name": p["display_name"], "roles": p["primary_roles"],
           "imdb_nconst": p["imdb_nconst"], "credit_count_catalog": p["credit_count"],
           "career_first_feature_year": p["career_first_feature_year"]}

    # ── catalog footprint (title_credit) ──
    cr = c.execute("""SELECT t.id tid, t.title, t.year, tc.role
                      FROM title_credit tc JOIN title t ON t.id = tc.title_id
                      WHERE tc.person_id = ?""", (pid,)).fetchall()
    titles = {r["tid"]: r["year"] for r in cr}
    years = [y for y in titles.values() if y]
    out["projects"] = len(titles)
    out["credits"] = len(cr)
    out["roles_breakdown"] = pd.Series([r["role"] for r in cr]).value_counts().to_dict() if cr else {}
    out["catalog_year_min"], out["catalog_year_max"] = (min(years), max(years)) if years else (None, None)
    span = (out["catalog_year_max"] - out["catalog_year_min"] + 1) if years else 0
    out["projects_per_year"] = round(len(titles) / span, 2) if span else None

    # ── real career (IMDb careers fold) ──
    import json as _json
    out["career"] = _json.loads(p["career_json"]) if p["career_json"] else {}

    # ── KMÍ funding approvals (the headline for writers/producers) ──
    mine = _person_norms(c, pid)
    appr = []
    for a in c.execute("""SELECT year, family, amount_isk, project_title, writer, director, producer, company
                          FROM allocations"""):
        roles = []
        if mine & set(_names(a["writer"])):
            roles.append("handritshöfundur")
        if mine & set(_names(a["director"])):
            roles.append("leikstjóri")
        if mine & (set(_names(a["producer"])) | set(_names(a["company"]))):
            roles.append("framleiðandi")
        if roles:
            appr.append({"year": a["year"], "family": a["family"], "amount": a["amount_isk"] or 0,
                         "project": a["project_title"], "as": "/".join(roles)})
    out["kmi_approvals"] = len(appr)
    out["kmi_projects"] = len({a["project"] for a in appr})
    out["kmi_total_isk"] = sum(a["amount"] for a in appr)
    out["kmi_by_family"] = pd.Series([a["family"] for a in appr]).value_counts().to_dict() if appr else {}
    ay = [a["year"] for a in appr if a["year"]]
    out["kmi_first_year"], out["kmi_last_year"] = (min(ay), max(ay)) if ay else (None, None)
    out["kmi_rows"] = sorted(appr, key=lambda a: (a["year"] or 0, -a["amount"]))

    # ── top collaborators ──
    out["collaborators"] = [dict(r) for r in c.execute(
        """SELECT p2.id pid, p2.display_name name, COUNT(DISTINCT tc1.title_id) together
           FROM title_credit tc1 JOIN title_credit tc2
                ON tc2.title_id = tc1.title_id AND tc2.person_id != tc1.person_id
           JOIN person p2 ON p2.id = tc2.person_id
           WHERE tc1.person_id = ? GROUP BY tc2.person_id
           ORDER BY together DESC, name LIMIT 8""", (pid,)).fetchall()]
    c.close()
    return out


# ───────────────────────── Streamlit dossier ─────────────────────────
def render(st, db_path, pid: int):
    s = compute(db_path, pid)
    if not s:
        st.error("Engin manneskja fannst.")
        return
    st.title(s["name"])
    bits = [s["roles"] or ""]
    if s["imdb_nconst"]:
        bits.append(f"[IMDb](https://www.imdb.com/name/{s['imdb_nconst']})")
    st.caption(" · ".join(b for b in bits if b))

    # headline metrics
    m = st.columns(4)
    m[0].metric("Verkefni (í skrá)", s["projects"])
    m[1].metric("Framlög á ferli", s["credits"])
    first = s["career_first_feature_year"]
    m[2].metric("Fyrsta kvikmynd", int(first) if first else "—")
    m[3].metric("KMÍ úthlutanir", s["kmi_approvals"])

    if s["projects_per_year"]:
        yr = f"{s['catalog_year_min']}–{s['catalog_year_max']}"
        st.caption(f"Virk(ur) {yr} · að meðaltali **{s['projects_per_year']}** verkefni á ári · "
                   f"hlutverk: {', '.join(f'{k} ({v})' for k, v in s['roles_breakdown'].items())}")

    # real career first-feature per role (from IMDb)
    if s["career"]:
        rows = [f"**{r}**: frumraun {v['first_feature_year']} _{v.get('first_feature_title','')}_ "
                f"· {v.get('feature_count','?')} kvikmyndir í fullri lengd"
                for r, v in sorted(s["career"].items(), key=lambda kv: kv[1].get("first_feature_year", 9999))]
        st.markdown("**Ferill (IMDb):** " + " · ".join(rows))

    # ── KMÍ funding approvals — the headline for writers/producers ──
    st.subheader(f"KMÍ-úthlutanir — {s['kmi_approvals']} samþykktir á {s['kmi_projects']} verkefni")
    if s["kmi_approvals"]:
        cols = st.columns(3)
        cols[0].metric("Samtals", _isk(s["kmi_total_isk"]))
        cols[1].metric("Fyrsta / nýjasta", f"{s['kmi_first_year']}–{s['kmi_last_year']}")
        cols[2].metric("Verkefni styrkt", s["kmi_projects"])
        fam = ", ".join(f"{FAMILY_IS.get(k, k)} ×{v}" for k, v in s["kmi_by_family"].items())
        st.caption("Eftir tegund: " + fam)
        df = pd.DataFrame(s["kmi_rows"])
        df["family"] = df["family"].map(lambda f: FAMILY_IS.get(f, f))
        df["amount"] = df["amount"].map(_isk)
        df = df[["year", "project", "as", "family", "amount"]]
        df.columns = ["Ár", "Verkefni", "Sem", "Tegund", "Upphæð"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Engin KMÍ-úthlutun skráð (skráin nær 2015–2024).")

    # ── collaborators ──
    if s["collaborators"]:
        st.subheader("Samstarf — oftast með")
        cdf = pd.DataFrame(s["collaborators"])[["name", "together"]]
        cdf.columns = ["Aðili", "Sameiginleg verkefni"]
        st.dataframe(cdf, use_container_width=True, hide_index=True)

    with st.expander("📋 Texti fyrir fund (afritaðu)"):
        st.code(to_markdown(s), language="markdown")


def to_markdown(s: dict) -> str:
    L = [f"# {s['name']}", ""]
    if s["roles"]:
        L.append(f"_{s['roles']}_")
    L.append("")
    L.append(f"- **{s['projects']}** verkefni í skránni · **{s['credits']}** framlög"
             + (f" · virk(ur) {s['catalog_year_min']}–{s['catalog_year_max']}"
                f" (~{s['projects_per_year']}/ári)" if s["projects_per_year"] else ""))
    if s["career_first_feature_year"]:
        L.append(f"- Fyrsta kvikmynd í fullri lengd: **{int(s['career_first_feature_year'])}**")
    if s["kmi_approvals"]:
        fam = ", ".join(f"{FAMILY_IS.get(k, k)} ×{v}" for k, v in s["kmi_by_family"].items())
        L.append(f"- KMÍ: **{s['kmi_approvals']}** úthlutanir á {s['kmi_projects']} verkefni, "
                 f"{_isk(s['kmi_total_isk'])} samtals ({s['kmi_first_year']}–{s['kmi_last_year']}) — {fam}")
    if s["collaborators"]:
        top = ", ".join(f"{c['name']} ({c['together']})" for c in s["collaborators"][:5])
        L.append(f"- Helstu samstarfsaðilar: {top}")
    return "\n".join(L)
