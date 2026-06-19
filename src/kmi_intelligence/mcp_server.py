"""MCP server exposing the KMÍ knowledge base as tools.

Lets any MCP client (Claude Code/Desktop, Cursor, agents) query the knowledge base live
instead of pasting files. Reads build/kmi.db (stdlib sqlite3); `search` uses the local
multilingual embeddings.

Run (in .venv-rag, which has `mcp` + sentence-transformers):
  PYTHONPATH=src .venv-rag/bin/python -m kmi_intelligence.mcp_server

Client config (e.g. Claude Code .mcp.json):
  {"mcpServers": {"kmi-intelligence": {
     "command": "<repo>/.venv-rag/bin/python",
     "args": ["-m", "kmi_intelligence.mcp_server"],
     "env": {"PYTHONPATH": "<repo>/src"}}}}
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "build" / "kmi.db"

mcp = FastMCP("kmi-intelligence")


def _c() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


@mcp.tool()
def list_grants(family: str = "") -> list[dict]:
    """List KMÍ grant streams (gáttir). Optional family filter:
    handrit | throun | framleidsla | eftirvinnsla | endurgreidsla | annad."""
    sql = "SELECT gatta_id, name_is, name_en, family, stage, max_amount_isk FROM grant_streams"
    p = ()
    if family:
        sql += " WHERE family=?"
        p = (family,)
    sql += " ORDER BY family, stage, level"
    with _c() as c:
        return [dict(r) for r in c.execute(sql, p)]


@mcp.tool()
def get_grant(gatta_or_name: str) -> dict:
    """Full detail for one grant stream by gátta ID (e.g. 'CUPCLS') or name substring:
    amount + basis, payment split, rules, every required/optional document WITH its spec
    (what it must prove, limits, file-naming), and the apply URL."""
    with _c() as c:
        s = c.execute("SELECT * FROM grant_streams WHERE gatta_id=? COLLATE NOCASE", (gatta_or_name,)).fetchone()
        if not s:
            s = c.execute("SELECT * FROM grant_streams WHERE name_is LIKE ? LIMIT 1", (f"%{gatta_or_name}%",)).fetchone()
        if not s:
            return {"error": f"no grant matching {gatta_or_name!r}", "hint": "call list_grants()"}
        out = dict(s)
        out["rules"] = json.loads(out.pop("rules_json") or "{}")
        docs = []
        for d in c.execute("SELECT requirement_level, document_text, doc_key FROM stream_documents WHERE stream_id=? ORDER BY rowid", (s["id"],)):
            item = {"level": d["requirement_level"], "name": d["document_text"]}
            if d["doc_key"]:
                spec = c.execute("SELECT what_it_must_prove, format_limit, naming_convention, common_weaknesses FROM documents WHERE doc_key=?", (d["doc_key"],)).fetchone()
                if spec:
                    item["spec"] = dict(spec)
            docs.append(item)
        out["documents"] = docs
        return out


@mcp.tool()
def get_document_spec(name_or_key: str) -> dict:
    """Spec for a document type (purpose, what it must prove, page/format limit, file-naming,
    common weaknesses). Accepts a doc_key or a name substring (e.g. 'synopsis', 'treatment')."""
    with _c() as c:
        r = c.execute("SELECT * FROM documents WHERE doc_key=? OR name_is LIKE ? OR name_en LIKE ? LIMIT 1",
                      (name_or_key, f"%{name_or_key}%", f"%{name_or_key}%")).fetchone()
        return dict(r) if r else {"error": f"no document matching {name_or_key!r}"}


@mcp.tool()
def funding_stats(family: str = "", year: int = 0, company: str = "") -> dict:
    """Aggregate historical funding (úthlutanir 2021–2024): totals, counts, by-family and
    by-year breakdowns, optionally filtered by family, year, and/or company substring."""
    where, p = ["amount_isk IS NOT NULL"], []
    if family:
        where.append("family=?"); p.append(family)
    if year:
        where.append("year=?"); p.append(year)
    if company:
        where.append("company LIKE ?"); p.append(f"%{company}%")
    w = " AND ".join(where)
    with _c() as c:
        tot = c.execute(f"SELECT COUNT(*) n, SUM(amount_isk) s FROM allocations WHERE {w}", p).fetchone()
        by_fam = [dict(r) for r in c.execute(f"SELECT family, COUNT(*) awards, SUM(amount_isk) total FROM allocations WHERE {w} GROUP BY family ORDER BY total DESC", p)]
        by_year = [dict(r) for r in c.execute(f"SELECT year, COUNT(*) awards, SUM(amount_isk) total FROM allocations WHERE {w} GROUP BY year ORDER BY year", p)]
        return {"awards": tot["n"], "total_isk": tot["s"], "by_family": by_fam, "by_year": by_year}


@mcp.tool()
def top_recipients(n: int = 10, family: str = "") -> list[dict]:
    """Companies that received the most total grant money (optionally within a family)."""
    where, p = ["amount_isk IS NOT NULL", "company IS NOT NULL"], []
    if family:
        where.append("family=?"); p.append(family)
    with _c() as c:
        return [dict(r) for r in c.execute(
            f"SELECT company, COUNT(*) awards, SUM(amount_isk) total FROM allocations WHERE {' AND '.join(where)} GROUP BY company ORDER BY total DESC LIMIT ?",
            (*p, n))]


@mcp.tool()
def lookup_person(name: str) -> dict:
    """Dossier for a film/TV person: roles, full filmography (year + role + whether the title was
    KMÍ-funded), and frequent collaborators. Built from title_credit (úthlutanir + catalog).
    Note: name-based resolution; two people with the same name may merge (ER is title/name-based)."""
    with _c() as c:
        p = c.execute("SELECT * FROM person WHERE display_name LIKE ? ORDER BY credit_count DESC LIMIT 1",
                      (f"%{name}%",)).fetchone()
        if not p:
            return {"error": f"no person matching {name!r}"}
        d = dict(p)
        d["filmography"] = [dict(r) for r in c.execute(
            "SELECT t.title, t.year, t.kind, tc.role, t.kmi_funded FROM title_credit tc JOIN title t ON t.id=tc.title_id "
            "WHERE tc.person_id=? ORDER BY t.year DESC, t.title", (p["id"],))]
        d["frequent_collaborators"] = [dict(r) for r in c.execute(
            "SELECT p2.display_name AS name, COUNT(*) AS together FROM title_credit c1 "
            "JOIN title_credit c2 ON c1.title_id=c2.title_id AND c1.person_id<>c2.person_id "
            "JOIN person p2 ON p2.id=c2.person_id WHERE c1.person_id=? "
            "GROUP BY c2.person_id ORDER BY together DESC LIMIT 8", (p["id"],))]
        return d


@mcp.tool()
def lookup_company(name: str) -> dict:
    """Dossier for an Icelandic production company: SÍK membership + contact, KMÍ funding rollup,
    the funded projects, and any unresolved name-variant merge candidates (entity resolution is
    title/name-based; variants from the úthlutanir PDFs are parked for review, not auto-merged)."""
    with _c() as c:
        co = c.execute("SELECT * FROM company WHERE name LIKE ? ORDER BY kmi_total_isk DESC LIMIT 1",
                       (f"%{name}%",)).fetchone()
        if not co:
            return {"error": f"no company matching {name!r}"}
        d = dict(co)
        raws = [r[0] for r in c.execute(
            "SELECT raw_string FROM alias WHERE entity_type='company' AND entity_id=? AND status='resolved'", (co["id"],))]
        if raws:
            qm = ",".join("?" * len(raws))
            d["funded_projects"] = [dict(r) for r in c.execute(
                f"SELECT DISTINCT project_title, year, amount_isk, family FROM allocations "
                f"WHERE company IN ({qm}) AND amount_isk IS NOT NULL ORDER BY year DESC, amount_isk DESC", raws)]
        d["merge_candidates"] = [r[0] for r in c.execute(
            "SELECT DISTINCT raw_string FROM alias WHERE entity_type='company' AND entity_id=? AND status='unresolved'", (co["id"],))]
        return d


@mcp.tool()
def get_rebate() -> dict:
    """The Icelandic production rebate (endurgreiðslukerfi): rates and the conditions for the
    enhanced 35% rate."""
    with _c() as c:
        return dict(c.execute("SELECT name_is, general_pct, general_basis, enhanced_pct, enhanced_conditions, regla_18_manuda FROM rebate").fetchone())


@mcp.tool()
def productions(funded: str = "", kind: str = "", min_year: int = 0, limit: int = 50) -> list[dict]:
    """Icelandic films + series (kvikmyndir.is series list + Wikipedia film list) cross-referenced
    with the KMÍ funding ledger.
    `kind`: '' = all, 'film', or 'series'.
    `funded`: '' = all; 'yes' = matched a KMÍ grant; 'no' = `likely_unfunded` (year ≥2022, no
    match — the real 'made without a grant' signal); 'unknown' = `ledger_gap` (pre-2021 release;
    our grant ledger only covers 2021-2024, so funding can't be assessed).
    Caveat: matching is title+year, so a title funded under a working title can read as unmatched."""
    where, p = ["1=1"], []
    if kind:
        where.append("kind=?"); p.append(kind)
    if min_year:
        where.append("year>=?"); p.append(min_year)
    if funded == "yes":
        where.append("kmi_funded=1")
    elif funded == "no":
        where.append("xref_status='likely_unfunded'")
    elif funded == "unknown":
        where.append("xref_status='ledger_gap'")
    with _c() as c:
        return [dict(r) for r in c.execute(
            f"SELECT title, year, kind, director, kmi_funded, kmi_total_isk, kmi_years_json, xref_status, match_confidence "
            f"FROM productions WHERE {' AND '.join(where)} ORDER BY year DESC, title LIMIT ?", (*p, limit))]


@mcp.tool()
def search(query: str, k: int = 5) -> list[dict]:
    """Semantic search across grants, documents, the rebate, process and the 793 historical
    awards (multilingual; Icelandic or English). Returns the best-matching chunks."""
    from . import rag
    if not rag.INDEX.exists():
        return [{"error": "no embeddings index — run `make embed` first"}]
    return rag.search(query, backend="local", k=k)


if __name__ == "__main__":
    mcp.run()
