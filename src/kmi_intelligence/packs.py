"""Generate prompt packs from build/kmi.db (see docs/ARCHITECTURE.md).

Outputs (build/prompt_packs/):
  kmi_context.md        master digest — drop into any project's prompt
  catalog.md / .json    full grant catalog (families + streams + documents)
  funding_patterns.md / .json   ledger analytics (what KMÍ funds, to whom, how much)
  streams/<GATTA>.md    one focused brief per application stream

These are DENORMALIZED, LLM-ready bundles. Every file carries a provenance +
confidence disclaimer because most catalog facts are confidence=needs_verification.

Stdlib only. Run: python -m kmi_intelligence.packs   (after `make build`)
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "kmi.db"
OUT = ROOT / "build" / "prompt_packs"
EXPORT = ROOT / "export"   # COMMITTED, stable drop-in files for other projects

DISCLAIMER = (
    "> **Source & confidence:** Generated from the KMÍ Intelligence knowledge base "
    "(`build/kmi.db`). Catalog facts are curated from official KMÍ sources but most are "
    "`needs_verification` — confirm amounts, deadlines and eligibility against the live "
    "umsóknargátt before relying on them. Ledger figures are parsed from the official "
    "úthlutanir PDFs (2021–2024)."
)
FAMILY_LABEL = {
    "handrit": "Handritsstyrkir (screenwriting)",
    "throun": "Þróunarstyrkir (development)",
    "framleidsla": "Framleiðslustyrkir (production)",
    "eftirvinnsla": "Eftirvinnslustyrkir (post-production)",
    "endurgreidsla": "Endurgreiðslur (rebate)",
    "annad": "Aðrir styrkir (other)",
}
DOC_LABEL = {"required": "Required", "newcomer": "Newcomer extra", "optional": "Optional",
             "recommended": "Recommended", "strategic": "Strategic"}


def isk(n) -> str:
    return f"{n:,.0f} ISK".replace(",", ".") if n else "—"


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def docs_for(c, stream_id):
    out = {}
    for r in c.execute("SELECT requirement_level, document_text FROM stream_documents WHERE stream_id=? ORDER BY rowid", (stream_id,)):
        out.setdefault(r["requirement_level"], []).append(r["document_text"])
    return out


# ---------------- per-stream briefs ----------------
def write_stream_briefs(c):
    d = OUT / "streams"
    d.mkdir(parents=True, exist_ok=True)
    for s in c.execute("SELECT * FROM grant_streams ORDER BY family, stage, level"):
        docs = docs_for(c, s["id"])
        lines = [f"# {s['name_is']}", ""]
        if s["name_en"]:
            lines.append(f"*{s['name_en']}*\n")
        lines += [
            f"- **Gátta ID:** `{s['gatta_id']}`",
            f"- **Family / stage:** {FAMILY_LABEL.get(s['family'], s['family'])} · {s['stage']}",
            f"- **Format:** {s['format_track']}",
            f"- **Max amount:** {isk(s['max_amount_isk'])}",
        ]
        if s["payment_split"]:
            lines.append(f"- **Payment split:** {s['payment_split']}")
        lines.append(f"- **Portal:** {s['portal_url']}")
        lines.append(f"- **Confidence:** {s['confidence']}")
        lines.append("")
        if s["purpose"]:
            lines += [f"**Purpose (markmið):** {s['purpose']}", ""]
        rules = json.loads(s["rules_json"] or "{}")
        if rules:
            lines.append("**Rules / conditions:**")
            for k, v in rules.items():
                lines.append(f"- *{k}:* {v}")
            lines.append("")
        if s["notes"]:
            lines += [f"**Notes:** {s['notes']}", ""]
        if docs:
            lines.append("**Documents (fylgigögn):**")
            for level in ("required", "newcomer", "recommended", "strategic", "optional"):
                if level in docs:
                    lines.append(f"\n*{DOC_LABEL.get(level, level)}:*")
                    lines += [f"- {x}" for x in docs[level]]
            lines.append("")
        lines.append(DISCLAIMER)
        (d / f"{s['gatta_id']}.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------- full catalog ----------------
def write_catalog(c):
    cat = {"families": [], "streams": [], "rebate": None, "process": []}
    md = ["# KMÍ grant catalog", "", DISCLAIMER, ""]
    for f in c.execute("SELECT * FROM grant_families ORDER BY id"):
        cat["families"].append(dict(f))
        md.append(f"## {f['name_is']} — {f['name_en']}")
        md.append(f"{f['purpose']}\n")
        md.append("| Gátta | Stream | Stage | Max amount | Split |")
        md.append("|---|---|---|---|---|")
        for s in c.execute("SELECT * FROM grant_streams WHERE family=? ORDER BY stage, level", (f["id"],)):
            row = dict(s)
            row["documents"] = docs_for(c, s["id"])
            cat["streams"].append(row)
            md.append(f"| `{s['gatta_id']}` | {s['name_is']} | {s['stage']} | {isk(s['max_amount_isk'])} | {s['payment_split'] or '—'} |")
        md.append("")
    r = c.execute("SELECT * FROM rebate").fetchone()
    if r:
        cat["rebate"] = dict(r)
        md += ["## Endurgreiðslur (rebate)",
               f"- General: **{r['general_pct']}%** {r['general_basis']}",
               f"- Enhanced: **{r['enhanced_pct']}%** — {r['enhanced_conditions']}",
               f"- 18-month rule: {r['regla_18_manuda']}", ""]
    for st in c.execute("SELECT * FROM process_stages ORDER BY ord"):
        cat["process"].append(dict(st))
    (OUT / "catalog.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- funding patterns (ledger) ----------------
def write_funding(c):
    data = {}
    md = ["# KMÍ funding patterns (úthlutanir 2021–2024)", "", DISCLAIMER, ""]

    by_year = [dict(r) for r in c.execute(
        "SELECT year, COUNT(*) awards, SUM(amount_isk) total FROM allocations WHERE amount_isk IS NOT NULL GROUP BY year ORDER BY year")]
    data["by_year"] = by_year
    md += ["## Total disbursed by year (styrkur)", "", "| Year | Awards | Total |", "|---|---|---|"]
    md += [f"| {r['year']} | {r['awards']} | {isk(r['total'])} |" for r in by_year]
    md.append("")

    by_fam = [dict(r) for r in c.execute(
        "SELECT family, COUNT(*) awards, SUM(amount_isk) total FROM allocations WHERE amount_isk IS NOT NULL GROUP BY family ORDER BY total DESC")]
    data["by_family"] = by_fam
    md += ["## By grant family (all years)", "", "| Family | Awards | Total |", "|---|---|---|"]
    md += [f"| {FAMILY_LABEL.get(r['family'], r['family'])} | {r['awards']} | {isk(r['total'])} |" for r in by_fam]
    md.append("")

    top = [dict(r) for r in c.execute(
        """SELECT company, COUNT(*) awards, SUM(amount_isk) total FROM allocations
           WHERE company IS NOT NULL AND amount_isk IS NOT NULL
           GROUP BY company ORDER BY total DESC LIMIT 20""")]
    data["top_companies"] = top
    md += ["## Top 20 companies by total grant", "", "| Total | Awards | Company |", "|---|---|---|"]
    md += [f"| {isk(r['total'])} | {r['awards']} | {r['company']} |" for r in top]
    md.append("")

    largest = [dict(r) for r in c.execute(
        "SELECT year, project_title, company, amount_isk FROM allocations WHERE amount_isk IS NOT NULL ORDER BY amount_isk DESC LIMIT 15")]
    data["largest_awards"] = largest
    md += ["## Largest single awards", "", "| Year | Amount | Project | Company |", "|---|---|---|---|"]
    md += [f"| {r['year']} | {isk(r['amount_isk'])} | {r['project_title']} | {r['company']} |" for r in largest]
    md.append("")

    # median/avg production grant by family
    stats = {}
    for fam in ("framleidsla", "throun", "handrit"):
        vals = [r["amount_isk"] for r in c.execute(
            "SELECT amount_isk FROM allocations WHERE family=? AND amount_isk IS NOT NULL", (fam,))]
        if vals:
            stats[fam] = {"n": len(vals), "mean": round(statistics.mean(vals)),
                          "median": round(statistics.median(vals)), "max": max(vals)}
    data["stats_by_family"] = stats
    md += ["## Grant size by family (styrkur)", "", "| Family | N | Mean | Median | Max |", "|---|---|---|---|---|"]
    md += [f"| {FAMILY_LABEL.get(k, k)} | {v['n']} | {isk(v['mean'])} | {isk(v['median'])} | {isk(v['max'])} |"
           for k, v in stats.items()]
    md.append("")

    (OUT / "funding_patterns.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "funding_patterns.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return by_year, top


# ---------------- master context digest ----------------
def write_master(c, by_year, top):
    md = ["# KMÍ Intelligence — context digest", "",
          "Knowledge base on Kvikmyndamiðstöð Íslands (KMÍ / Icelandic Film Centre): "
          "what it funds, how to apply, and what it has funded (2021–2024).", "", DISCLAIMER, "",
          "## Grant streams (gáttir)", "", "| Gátta | Stream | Stage | Max amount |", "|---|---|---|---|"]
    for s in c.execute("SELECT gatta_id, name_is, stage, max_amount_isk FROM grant_streams ORDER BY family, stage, level"):
        md.append(f"| `{s['gatta_id']}` | {s['name_is']} | {s['stage']} | {isk(s['max_amount_isk'])} |")
    r = c.execute("SELECT * FROM rebate").fetchone()
    md += ["", "## Rebate", f"- {r['general_pct']}% general / {r['enhanced_pct']}% enhanced of approved Icelandic spend.", ""]
    md += ["## Funding headline (úthlutanir)", "", "| Year | Awards | Total |", "|---|---|---|"]
    md += [f"| {x['year']} | {x['awards']} | {isk(x['total'])} |" for x in by_year]
    md += ["", "**Most-funded companies:** " + ", ".join(f"{t['company']} ({isk(t['total'])})" for t in top[:6]), ""]
    md += ["## Application & delivery process", ""]
    for st in c.execute("SELECT name_is, condition FROM process_stages ORDER BY ord"):
        md.append(f"- **{st['name_is']}** — {st['condition'] or ''}")
    md += ["", "See `catalog.md`, `funding_patterns.md`, and `streams/<GATTA>.md` for detail."]
    (OUT / "kmi_context.md").write_text("\n".join(md), encoding="utf-8")


def _doc_specs(c):
    return {r["doc_key"]: dict(r) for r in c.execute("SELECT * FROM documents") if r["doc_key"]}


def _howto(kind: str) -> str:
    return (f"<!-- KMÍ Intelligence — {kind}. Generated {date.today()}. -->\n\n"
            "> **How to use:** drop this into an AI prompt or project as authoritative context on "
            "Icelandic Film Centre (KMÍ) grants — what each grant funds, the documents required "
            "(with specs + file-naming), amounts, the production rebate, the application/delivery "
            "process, and historical funding (2021–2024).\n>\n"
            "> **Confidence:** facts are labelled `verified` (quoted from an official source), "
            "`needs_verification` (from a real source, unchecked), or `inferred`. Treat amounts and "
            "deadlines as guidance — confirm on the live umsóknargátt before relying on them.\n")


def write_export(c, by_year, top):
    EXPORT.mkdir(parents=True, exist_ok=True)
    specs = _doc_specs(c)
    DOC_ORDER = ("required", "newcomer", "recommended", "strategic", "optional")

    # ---------- kmi_full.md : EVERYTHING in one file ----------
    md = [_howto("full knowledge pack"), "# KMÍ grant knowledge base\n"]
    md.append("## 1. Grants (gáttir) — requirements & amounts\n")
    for f in c.execute("SELECT * FROM grant_families ORDER BY id"):
        streams = c.execute("SELECT * FROM grant_streams WHERE family=? ORDER BY stage, level", (f["id"],)).fetchall()
        if not streams:
            continue
        md.append(f"### {f['name_is']} — {f['name_en']}\n{f['purpose']}\n")
        for s in streams:
            md.append(f"#### {s['name_is']}  ·  `{s['gatta_id']}`")
            mx = isk(s["max_amount_isk"]) if s["max_amount_isk"] else "scope-dependent (fer eftir umfangi)"
            md.append(f"- **Application max:** {mx}" + (f"  \n  _{s['amount_basis']}_" if s["amount_basis"] else ""))
            if s["payment_split"]:
                md.append(f"- **Payment split:** {s['payment_split']}")
            if s["purpose"]:
                md.append(f"- **Purpose:** {s['purpose']}")
            for k_, v_ in json.loads(s["rules_json"] or "{}").items():
                md.append(f"- **{k_}:** {v_}")
            if s["portal_url"]:
                md.append(f"- **Apply:** {s['portal_url']}")
            docs = docs_for(c, s["id"])
            for lvl in DOC_ORDER:
                for txt in docs.get(lvl, []):
                    md.append(f"  - [{lvl}] {txt}")
            md.append(f"- _confidence: {s['confidence']}_\n")

    md.append("## 2. Document specifications\n")
    md.append("Every document referenced above, with what it must prove, limits, and file-naming.\n")
    for d in c.execute("SELECT * FROM documents ORDER BY name_is"):
        md.append(f"### {d['name_is']} ({d['name_en']})")
        md.append(f"- **Purpose:** {d['purpose']}")
        md.append(f"- **Must prove:** {d['what_it_must_prove']}")
        if d["format_limit"] and d["format_limit"] != "—":
            md.append(f"- **Format/limit:** {d['format_limit']}")
        md.append(f"- **File name:** `{d['naming_convention']}`")
        if d["common_weaknesses"]:
            md.append(f"- **Common weaknesses:** {d['common_weaknesses']}")
        md.append("")

    md.append("## 3. Evaluation criteria (what advisors weigh)\n")
    for cr in c.execute("SELECT * FROM criteria"):
        md.append(f"### {cr['name_is']} ({cr['name_en']})\n{cr['description']}")
        md.append(f"- **Evidence of strength:** {cr['evidence_examples']}")
        md.append(f"- **Red flags:** {cr['red_flags']}\n")

    md.append("## 4. Amounts\n### Application maxima (per gátta)\n")
    md.append("| Gátta | Stream | Max | Basis |\n|---|---|---|---|")
    for s in c.execute("SELECT gatta_id,name_is,max_amount_isk,amount_basis FROM grant_streams WHERE family IN ('handrit','throun','eftirvinnsla') ORDER BY format_track,stage,level"):
        mx = isk(s["max_amount_isk"]) if s["max_amount_isk"] else "scope-dependent"
        md.append(f"| `{s['gatta_id']}` | {s['name_is']} | {mx} | {(s['amount_basis'] or '')[:80]} |")
    md.append("\n### Disbursement history (verbatim from úthlutanir PDFs)\n")
    md.append("| Family | Format | Year | Parts | Total |\n|---|---|---|---|---|")
    for a in c.execute("SELECT family,format_track,year,parts_json,total_isk FROM grant_amounts ORDER BY family,format_track,year"):
        md.append(f"| {a['family']} | {a['format_track']} | {a['year']} | {a['parts_json']} | {isk(a['total_isk'])} |")

    r = c.execute("SELECT * FROM rebate").fetchone()
    md.append(f"\n## 5. Production rebate\n- **{r['general_pct']}%** general — {r['general_basis']}\n- **{r['enhanced_pct']}%** enhanced — {r['enhanced_conditions']}\n- {r['regla_18_manuda']}\n")

    md.append("## 6. Application & delivery process\n")
    for st in c.execute("SELECT * FROM process_stages ORDER BY ord"):
        md.append(f"**{st['ord']}. {st['name_is']}** — {st['condition'] or ''}"
                  + (f" (frestur {st['deadline_months']} mán.)" if st["deadline_months"] else ""))
    md.append("")

    md.append("## 7. Funding patterns (úthlutanir 2021–2024)\n")
    md.append("| Year | Awards | Total |\n|---|---|---|")
    md += [f"| {x['year']} | {x['awards']} | {isk(x['total'])} |" for x in by_year]
    md.append("\n**Most-funded companies:** " + ", ".join(f"{t['company']} ({isk(t['total'])})" for t in top[:8]))
    (EXPORT / "kmi_full.md").write_text("\n".join(md), encoding="utf-8")

    # ---------- kmi_full.json : structured twin ----------
    streams_json = []
    for s in c.execute("SELECT * FROM grant_streams ORDER BY family, stage, level"):
        row = dict(s)
        row["rules"] = json.loads(row.pop("rules_json") or "{}")
        row["documents"] = {lvl: [{"text": t, "spec": specs.get(
            c.execute("SELECT doc_key FROM stream_documents WHERE stream_id=? AND document_text=?", (s["id"], t)).fetchone()[0])}
            for t in lst] for lvl, lst in docs_for(c, s["id"]).items()}
        streams_json.append(row)
    full = {
        "_meta": {"generated": str(date.today()),
                  "about": "KMÍ (Icelandic Film Centre) grant knowledge base — catalog, documents, amounts, rebate, process, funding.",
                  "confidence_legend": ["verified", "needs_verification", "inferred", "sample"]},
        "families": [dict(r) for r in c.execute("SELECT * FROM grant_families ORDER BY id")],
        "streams": streams_json,
        "documents": [dict(r) for r in c.execute("SELECT * FROM documents ORDER BY name_is")],
        "criteria": [dict(r) for r in c.execute("SELECT * FROM criteria")],
        "amounts_disbursement": [dict(r) for r in c.execute("SELECT * FROM grant_amounts ORDER BY family,format_track,year")],
        "rebate": dict(c.execute("SELECT * FROM rebate").fetchone()),
        "process": [dict(r) for r in c.execute("SELECT * FROM process_stages ORDER BY ord")],
        "funding": {
            "by_year": [dict(r) for r in by_year.to_dict("records")] if hasattr(by_year, "to_dict") else by_year,
            "top_companies": [dict(r) for r in (top.to_dict("records") if hasattr(top, "to_dict") else top)],
        },
    }
    (EXPORT / "kmi_full.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- kmi_context.md : compact digest ----------
    ctx = [_howto("compact digest"), "# KMÍ grants — quick reference\n", "## Streams (gáttir)\n",
           "| Gátta | Stream | Stage | Max |\n|---|---|---|---|"]
    for s in c.execute("SELECT gatta_id,name_is,stage,max_amount_isk FROM grant_streams ORDER BY family,stage,level"):
        ctx.append(f"| `{s['gatta_id']}` | {s['name_is']} | {s['stage']} | {isk(s['max_amount_isk']) if s['max_amount_isk'] else 'scope-dep.'} |")
    ctx.append(f"\n**Rebate:** {r['general_pct']}% / {r['enhanced_pct']}% (enhanced needs ≥350M spend, ≥10/≥30 days, ≥50 staff).")
    ctx.append("\n**Funding (úthlutanir):** " + "; ".join(f"{x['year']}: {isk(x['total'])}" for x in by_year))
    ctx.append("\nFor full document specs, criteria, amounts and process see `kmi_full.md` / `kmi_full.json`.")
    (EXPORT / "kmi_context.md").write_text("\n".join(ctx), encoding="utf-8")


def main() -> int:
    if not DB_PATH.exists():
        print("build/kmi.db not found — run `make build` first.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    c = conn()
    write_stream_briefs(c)
    write_catalog(c)
    by_year, top = write_funding(c)
    write_master(c, by_year, top)
    write_export(c, by_year, top)
    n_streams = c.execute("SELECT COUNT(*) FROM grant_streams").fetchone()[0]
    print(f"Wrote prompt packs -> {OUT.relative_to(ROOT)}")
    print(f"  kmi_context.md, catalog.md/.json, funding_patterns.md/.json, streams/*.md ({n_streams} briefs)")
    print(f"Wrote committed export -> {EXPORT.relative_to(ROOT)}")
    print("  kmi_context.md, kmi_full.md, kmi_full.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
