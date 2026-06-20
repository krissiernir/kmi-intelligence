"""make health — the data-health cockpit over build/kmi.db.

One place to TRUST the knowledge base as it grows. Reports, per run:
  • zone counts + key integrity (Zone 1 grant core must hold floors)
  • coverage (IMDb tconst/enrichment; Klapptré fact→entity resolution rates)
  • source freshness (every sources.json local_path: present? how many raw files?)
  • human-review queues (unresolved aliases, parked tconst candidates)
  • sanity alarms (e.g. admissions > 500k = mislabeled ISK gross)
  • DRIFT: diff every metric against the previous run (build/health_snapshot.json)

Writes build/HEALTH.md + prints a ✓/⚠/✗ summary. Stdlib only. Read-only over the DB.
Run: python -m kmi_intelligence.health   (or `make health`)
"""
from __future__ import annotations

import glob
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "build" / "kmi.db"
SNAP = ROOT / "build" / "health_snapshot.json"
OUT = ROOT / "build" / "HEALTH.md"

OK, WARN, FAIL = "✓", "⚠", "✗"


def _count(c, t):
    try:
        return c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except sqlite3.OperationalError:
        return None


def collect(c) -> dict:
    m = {}
    for t in ("sources", "grant_families", "grant_streams", "stream_documents", "documents",
              "criteria", "grant_amounts", "allocations", "rebate_stages", "process_stages",
              "title", "person", "company", "title_credit", "title_company", "award", "alias",
              "corpus_article", "corpus_mention", "lx_admissions", "lx_viewership", "lx_review",
              "lx_award"):
        n = _count(c, t)
        if n is not None:
            m[t] = n

    def one(q, d=0):
        try:
            v = c.execute(q).fetchone()[0]
            return v if v is not None else d
        except sqlite3.OperationalError:
            return d

    m["doc_key_match_pct"] = round(100 * one("SELECT COUNT(*) FROM stream_documents WHERE doc_key IS NOT NULL")
                                   / max(1, m.get("stream_documents", 1)), 1)
    cat = one("SELECT COUNT(*) FROM title WHERE source IN('src.kvikmyndir_is','src.wikipedia_is')")
    m["catalog_titles"] = cat
    m["catalog_with_tconst"] = one("SELECT COUNT(*) FROM title WHERE source IN('src.kvikmyndir_is','src.wikipedia_is') AND imdb_tconst LIKE 'tt%'")
    m["titles_enriched"] = one("SELECT COUNT(*) FROM title WHERE imdb_enriched=1")
    m["alias_unresolved"] = one("SELECT COUNT(*) FROM alias WHERE status='unresolved'")
    m["adm_resolved"] = one("SELECT COUNT(*) FROM lx_admissions WHERE title_id IS NOT NULL")
    m["adm_total_rows"] = m.get("lx_admissions", 0)
    m["review_resolved"] = one("SELECT COUNT(*) FROM lx_review WHERE title_id IS NOT NULL")
    m["award_resolved"] = one("SELECT COUNT(*) FROM lx_award WHERE title_id IS NOT NULL OR person_id IS NOT NULL")
    m["adm_over_500k"] = one("SELECT COUNT(*) FROM lx_admissions WHERE total_admissions>500000 OR week_admissions>500000")
    m["alloc_no_amount"] = one("SELECT COUNT(*) FROM allocations WHERE amount_isk IS NULL AND commitment_isk IS NULL")
    return m


def checks(m: dict) -> list[tuple[str, str, str]]:
    r = []

    def chk(cond, name, detail):
        r.append((OK if cond else FAIL, name, detail))

    def warn(cond, name, detail):
        r.append((OK if cond else WARN, name, detail))

    # Zone 1 — grant core floors (these must not regress)
    chk(m.get("grant_families") == 6, "Zone1 families", f"{m.get('grant_families')} (expect 6)")
    chk(m.get("grant_streams", 0) >= 20, "Zone1 streams", f"{m.get('grant_streams')} (>=20)")
    chk(m.get("allocations", 0) >= 790, "Zone1 ledger", f"{m.get('allocations')} allocations (>=790)")
    warn(m.get("doc_key_match_pct", 0) >= 90, "Zone1 doc specs", f"{m.get('doc_key_match_pct')}% checklist→spec matched")
    # Zone 2
    chk(m.get("title", 0) >= 900, "Zone2 titles", f"{m.get('title')}")
    chk(m.get("title_credit", 0) > 0 and m.get("person", 0) > 0, "Zone2 spine", f"{m.get('person')} people / {m.get('title_credit')} credits")
    # Zone 3 sanity
    chk(m.get("adm_over_500k", 0) == 0, "Zone3 admissions sanity", f"{m.get('adm_over_500k')} rows >500k (mislabeled gross)")
    warn(m.get("corpus_article", 0) > 0, "Zone3 corpus", f"{m.get('corpus_article')} articles")
    return r


def coverage(m: dict) -> list[str]:
    def pct(a, b):
        return f"{round(100*a/max(1,b),1)}%"
    return [
        f"IMDb tconst coverage (catalog): {m.get('catalog_with_tconst')}/{m.get('catalog_titles')} ({pct(m.get('catalog_with_tconst',0), m.get('catalog_titles',1))})",
        f"IMDb enriched titles: {m.get('titles_enriched')}",
        f"Klapptré admissions → title: {m.get('adm_resolved')}/{m.get('adm_total_rows')} ({pct(m.get('adm_resolved',0), m.get('adm_total_rows',1))})",
        f"Klapptré reviews → title: {m.get('review_resolved')}/{m.get('lx_review',0)} ({pct(m.get('review_resolved',0), m.get('lx_review',1))})",
        f"Klapptré awards → title/person: {m.get('award_resolved')}/{m.get('lx_award',0)} ({pct(m.get('award_resolved',0), m.get('lx_award',1))})",
    ]


def _jlen(p, key=None):
    if not p.exists():
        return 0
    d = json.loads(p.read_text())
    return len(d.get(key, [])) if key else len(d)


def queues(m: dict) -> list[str]:
    cand = ROOT / "data" / "staged" / "merge_candidates.json"
    mrg = ROOT / "data" / "curated" / "entity_merges.json"
    return [
        f"Splink merge candidates to review (run `make review`): {_jlen(cand)}",
        f"  ↳ confirmed merges applied: {_jlen(mrg,'merges')} · kept-separate: {_jlen(mrg,'rejected')}",
        f"Unresolved entity aliases (legacy fuzzy queue): {m.get('alias_unresolved')}",
        f"Parked tconst candidates (imdb_resolve_review.json): {_jlen(ROOT/'data'/'staged'/'imdb_resolve_review.json')}",
        f"Allocations with no amount (vilyrði-only / parse gap): {m.get('alloc_no_amount')}",
    ]


def sources_health() -> list[tuple[str, str, str]]:
    sp = ROOT / "data" / "curated" / "sources.json"
    if not sp.exists():
        return []
    out = []
    for s in json.loads(sp.read_text()).get("sources", []):
        lp = s.get("local_path")
        if not lp:
            continue
        p = ROOT / lp
        if not p.exists():
            out.append((WARN, s["id"], f"local_path missing: {lp}"))
        elif p.is_dir():
            n = len(glob.glob(str(p / "*")))
            out.append((OK if n else WARN, s["id"], f"{n} files in {lp}"))
        else:
            out.append((OK, s["id"], lp))
    return out


def drift(m: dict) -> list[tuple[str, str, str]]:
    if not SNAP.exists():
        return [(OK, "baseline", "no previous snapshot — recording first baseline")]
    prev = json.loads(SNAP.read_text()).get("metrics", {})
    out = []
    for k, v in m.items():
        if not isinstance(v, (int, float)):
            continue
        pv = prev.get(k)
        if pv is None:
            out.append((OK, k, f"new metric = {v}"))
        elif pv and abs(v - pv) / max(1, pv) >= 0.10:
            lvl = WARN if v < pv else OK
            out.append((lvl, k, f"{pv} → {v} ({'+' if v>=pv else ''}{v-pv})"))
    return out or [(OK, "stable", "no metric moved >10% since last run")]


def main() -> int:
    if not DB.exists():
        print("build/kmi.db not found — run `make build` first.")
        return 1
    c = sqlite3.connect(DB)
    m = collect(c)
    chk, cov, q, src, dft = checks(m), coverage(m), queues(m), sources_health(), drift(m)
    fails = sum(1 for s, *_ in chk if s == FAIL)
    warns = sum(1 for s, *_ in chk + src + dft if s == WARN)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"# KMÍ Intelligence — data health  ({now})", "",
             f"**{fails} failures · {warns} warnings** across grant core, spine, and corpus.", "",
             "## Integrity checks"]
    lines += [f"- {s} **{n}** — {d}" for s, n, d in chk]
    lines += ["", "## Coverage"] + [f"- {x}" for x in cov]
    lines += ["", "## Human-review queues"] + [f"- {x}" for x in q]
    lines += ["", "## Source freshness"] + [f"- {s} `{n}` — {d}" for s, n, d in src]
    lines += ["", "## Drift vs last run"] + [f"- {s} {n}: {d}" for s, n, d in dft]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    SNAP.write_text(json.dumps({"at": now, "metrics": m}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"data health @ {now}  —  {fails} {FAIL}  ·  {warns} {WARN}")
    for s, n, d in chk:
        print(f"  {s} {n}: {d}")
    print("  coverage: " + " | ".join(cov[:3]))
    print(f"  queues: aliases={m.get('alias_unresolved')}  tconst-review={len(json.loads((ROOT/'data'/'staged'/'imdb_resolve_review.json').read_text())) if (ROOT/'data'/'staged'/'imdb_resolve_review.json').exists() else 0}")
    print(f"  full report -> {OUT.relative_to(ROOT)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
