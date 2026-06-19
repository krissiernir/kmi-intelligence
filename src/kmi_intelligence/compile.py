"""Compile the curated knowledge base (data/curated/*.json) into build/kmi.db.

This is the v2 build step (see docs/ARCHITECTURE.md). It defines its own clean,
TEXT-keyed schema and supersedes the integer-keyed MVP schema in db.py for the
real data foundation. The MVP db.py/seed.py remain for the legacy sample app.

Rules enforced:
- every record's _meta.sources[] must resolve to a source id in sources.json
  (build FAILS on a dangling reference);
- records with no sources or confidence are reported as warnings.

Stdlib only. Run: python -m kmi_intelligence.compile
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURATED = ROOT / "data" / "curated"
BUILD = ROOT / "build"
DB_PATH = BUILD / "kmi.db"

PORTAL_PATTERN = "https://umsokn.kvikmyndamidstod.is/web/portal/application.html?id={}"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    title TEXT, url TEXT, source_type TEXT,
    local_path TEXT, content_sha256 TEXT,
    fetched_at TEXT, checked_at TEXT, notes TEXT
);

CREATE TABLE grant_families (
    id TEXT PRIMARY KEY,
    name_is TEXT, name_en TEXT, purpose TEXT,
    format_tracks_json TEXT, subtypes_json TEXT,
    confidence TEXT, sources_json TEXT
);

CREATE TABLE grant_streams (
    id TEXT PRIMARY KEY,
    gatta_id TEXT, name_is TEXT, name_en TEXT,
    family TEXT, format_track TEXT, stage TEXT, level TEXT,
    portal_url TEXT, purpose TEXT,
    max_amount_isk INTEGER, amount_basis TEXT, payment_split TEXT,
    rules_json TEXT, notes TEXT,
    confidence TEXT, checked_at TEXT, sources_json TEXT,
    FOREIGN KEY (family) REFERENCES grant_families(id)
);

CREATE TABLE grant_amounts (
    family TEXT, format_track TEXT, year INTEGER, stage_note TEXT,
    structure TEXT, parts_json TEXT, total_isk INTEGER,
    quote TEXT, source TEXT, source_line INTEGER, confidence TEXT
);

CREATE TABLE stream_documents (
    stream_id TEXT, requirement_level TEXT, document_text TEXT, doc_key TEXT,
    FOREIGN KEY (stream_id) REFERENCES grant_streams(id)
);

CREATE TABLE documents (
    doc_key TEXT PRIMARY KEY, name_is TEXT, name_en TEXT, purpose TEXT,
    what_it_must_prove TEXT, format_limit TEXT, naming_convention TEXT,
    common_weaknesses TEXT, aliases_json TEXT, confidence TEXT, sources_json TEXT
);

CREATE TABLE criteria (
    id TEXT PRIMARY KEY, name_is TEXT, name_en TEXT, description TEXT,
    evidence_examples TEXT, red_flags TEXT, confidence TEXT, sources_json TEXT
);

CREATE TABLE rebate (
    id TEXT PRIMARY KEY, name_is TEXT, name_en TEXT,
    general_pct INTEGER, general_basis TEXT,
    enhanced_pct INTEGER, enhanced_conditions TEXT,
    regla_18_manuda TEXT, audit_trail TEXT,
    confidence TEXT, sources_json TEXT
);
CREATE TABLE rebate_stages (
    rebate_id TEXT, ord INTEGER, id TEXT,
    name_is TEXT, description TEXT, stream_id TEXT
);

CREATE TABLE process_stages (
    process_id TEXT, ord INTEGER, id TEXT, name_is TEXT,
    condition TEXT, deadline_months INTEGER,
    regulation_ref TEXT, submit_email TEXT
);
CREATE TABLE process_checklist (
    stage_id TEXT, title TEXT, description TEXT
);
CREATE TABLE process_forms (
    stage_id TEXT, title TEXT, format TEXT, url TEXT
);
CREATE TABLE film_archive_links (
    deposit_id TEXT, link_key TEXT, url TEXT
);

CREATE TABLE allocations (
    id INTEGER PRIMARY KEY,
    year INTEGER, project_title TEXT,
    family TEXT, subtype TEXT, format_track TEXT,
    applicant TEXT, company TEXT, producer TEXT, director TEXT, writer TEXT,
    amount_isk INTEGER, total_isk INTEGER,
    commitment_isk INTEGER, commitments_json TEXT,
    source_id TEXT, raw_line TEXT, confidence TEXT
);

CREATE TABLE title (
    id INTEGER PRIMARY KEY, kvik_id INTEGER, imdb_tconst TEXT,
    title TEXT, original_title TEXT, year INTEGER, kind TEXT, status TEXT, region TEXT DEFAULT 'IS',
    director TEXT, where_shown_json TEXT, og_type TEXT, url TEXT, source TEXT,
    kmi_funded INTEGER, kmi_alloc_count INTEGER, kmi_total_isk INTEGER,
    kmi_years_json TEXT, match_confidence TEXT, xref_status TEXT, matched_json TEXT,
    confidence TEXT,
    imdb_rating REAL, imdb_votes INTEGER, imdb_award_wins INTEGER, imdb_award_noms INTEGER,
    worldwide_gross_usd INTEGER, production_budget TEXT,
    imdb_genres_json TEXT, imdb_countries_json TEXT, imdb_akas_json TEXT, imdb_enriched INTEGER
);

CREATE TABLE person (
    id INTEGER PRIMARY KEY, display_name TEXT, name_norm TEXT, imdb_nconst TEXT,
    kvik_person_id TEXT, region TEXT DEFAULT 'IS', primary_roles TEXT, credit_count INTEGER,
    source TEXT, confidence TEXT
);

CREATE TABLE title_credit (title_id INTEGER, person_id INTEGER, role TEXT, job TEXT, source TEXT, confidence TEXT);
CREATE TABLE title_company (title_id INTEGER, company_id INTEGER, role TEXT, source TEXT, confidence TEXT);
CREATE TABLE award (title_id INTEGER, allocation_id INTEGER, year INTEGER, amount_isk INTEGER, family TEXT, source TEXT);

CREATE TABLE company (
    id INTEGER PRIMARY KEY, name TEXT, name_norm TEXT, type TEXT,
    is_sik_member INTEGER, website TEXT, email TEXT, phone TEXT, address TEXT,
    kmi_grants_count INTEGER, kmi_total_isk INTEGER, kmi_years_json TEXT,
    imdb_conmst TEXT, source TEXT, confidence TEXT
);

CREATE TABLE alias (
    entity_type TEXT, raw_string TEXT, raw_norm TEXT, entity_id INTEGER,
    source TEXT, match_method TEXT, confidence TEXT, status TEXT
);

CREATE VIEW productions AS SELECT * FROM title;

CREATE INDEX idx_streams_family ON grant_streams(family);
CREATE INDEX idx_company_norm ON company(name_norm);
CREATE INDEX idx_alias_norm ON alias(entity_type, raw_norm);
CREATE INDEX idx_streams_stage ON grant_streams(stage);
CREATE INDEX idx_docs_stream ON stream_documents(stream_id);
CREATE INDEX idx_alloc_year ON allocations(year);
CREATE INDEX idx_alloc_family ON allocations(family);
CREATE INDEX idx_title_norm ON title(title);
CREATE INDEX idx_credit_person ON title_credit(person_id);
CREATE INDEX idx_credit_title ON title_credit(title_id);
CREATE INDEX idx_credit_role ON title_credit(role);
CREATE INDEX idx_award_title ON award(title_id);
CREATE INDEX idx_person_nconst ON person(imdb_nconst);
CREATE INDEX idx_company_conmst ON company(imdb_conmst);
CREATE INDEX idx_title_tconst ON title(imdb_tconst);
"""

# document dict key -> requirement_level
DOC_LEVELS = {
    "required": "required",
    "recommended": "recommended",
    "strategic": "strategic",
    "newcomer_extra": "newcomer",
    "optional": "optional",
}


def load(name: str) -> dict:
    with open(CURATED / name, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    warnings: list[str] = []
    errors: list[str] = []

    sources_doc = load("sources.json")
    valid_source_ids = {s["id"] for s in sources_doc["sources"]}

    def check_meta(record_id: str, meta: dict | None) -> tuple[str, str]:
        """Validate provenance; return (confidence, sources_json)."""
        meta = meta or {}
        srcs = meta.get("sources", [])
        if not srcs:
            warnings.append(f"{record_id}: no sources in _meta")
        for sid in srcs:
            if sid not in valid_source_ids:
                errors.append(f"{record_id}: unknown source id '{sid}'")
        if not meta.get("confidence"):
            warnings.append(f"{record_id}: no confidence in _meta")
        return meta.get("confidence", ""), json.dumps(srcs, ensure_ascii=False)

    families = load("grant_families.json")["families"]
    streams_doc = load("grant_streams.json")
    default_meta = streams_doc.get("_default_meta", {})
    streams = streams_doc["streams"]
    rebate = load("rebate.json")["rebate"]
    process = load("process.json")
    amounts = load("grant_amounts.json")["amounts"]
    for i, a in enumerate(amounts):
        if a.get("source") not in valid_source_ids:
            errors.append(f"grant_amounts[{i}]: unknown source id '{a.get('source')}'")
    documents_doc = load("documents.json")
    documents = documents_doc["documents"]
    criteria_doc = load("criteria.json")
    criteria = criteria_doc["criteria"]

    # Validate everything BEFORE touching the DB.
    for f in families:
        check_meta(f"family:{f['id']}", f.get("_meta"))
    for s in streams:
        check_meta(f"stream:{s['id']}", s.get("_meta", default_meta))
    check_meta("rebate", rebate.get("_meta"))
    check_meta("process:contract", process["contract_process"].get("_meta"))
    check_meta("process:archive", process["film_archive_deposit"].get("_meta"))
    check_meta("documents", documents_doc.get("_meta"))
    check_meta("criteria", criteria_doc.get("_meta"))

    if errors:
        print("BUILD FAILED — dangling source references:")
        for e in errors:
            print("  ERROR", e)
        return 1

    BUILD.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # sources
    for s in sources_doc["sources"]:
        conn.execute(
            "INSERT INTO sources(id,title,url,source_type,local_path,content_sha256,fetched_at,checked_at,notes) VALUES(?,?,?,?,?,?,?,?,?)",
            (s["id"], s.get("title"), s.get("url"), s.get("source_type"), s.get("local_path"),
             s.get("content_sha256"), s.get("fetched_at"), s.get("checked_at"), s.get("notes")),
        )

    # families
    for f in families:
        conf, sj = check_meta(f"family:{f['id']}", f.get("_meta"))
        conn.execute(
            "INSERT INTO grant_families(id,name_is,name_en,purpose,format_tracks_json,subtypes_json,confidence,sources_json) VALUES(?,?,?,?,?,?,?,?)",
            (f["id"], f.get("name_is"), f.get("name_en"), f.get("purpose"),
             json.dumps(f.get("format_tracks", []), ensure_ascii=False),
             json.dumps(f.get("subtypes", []), ensure_ascii=False), conf, sj),
        )

    # documents (canonical specs) + criteria; build alias matcher for stream docs
    dconf, dsj = check_meta("documents", documents_doc.get("_meta"))
    alias_map = []  # (alias_lower, doc_key), longest-first for specificity
    for d in documents:
        conn.execute(
            "INSERT INTO documents(doc_key,name_is,name_en,purpose,what_it_must_prove,format_limit,naming_convention,common_weaknesses,aliases_json,confidence,sources_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (d["doc_key"], d.get("name_is"), d.get("name_en"), d.get("purpose"),
             d.get("what_it_must_prove"), d.get("format_limit"), d.get("naming_convention"),
             d.get("common_weaknesses"), json.dumps(d.get("aliases", []), ensure_ascii=False), dconf, dsj),
        )
        for a in d.get("aliases", []):
            alias_map.append((a.lower(), d["doc_key"]))
    alias_map.sort(key=lambda x: -len(x[0]))

    def match_doc(text: str):
        t = text.lower()
        for alias, key in alias_map:
            if alias in t:
                return key
        return None

    cconf, csj = check_meta("criteria", criteria_doc.get("_meta"))
    for cr in criteria:
        conn.execute(
            "INSERT INTO criteria(id,name_is,name_en,description,evidence_examples,red_flags,confidence,sources_json) VALUES(?,?,?,?,?,?,?,?)",
            (cr["id"], cr.get("name_is"), cr.get("name_en"), cr.get("description"),
             cr.get("evidence_examples"), cr.get("red_flags"), cconf, csj),
        )

    # streams + documents
    for s in streams:
        meta = s.get("_meta", default_meta)
        conf, sj = check_meta(f"stream:{s['id']}", meta)
        gatta = s.get("gatta_id")
        portal = s.get("portal_url") or (PORTAL_PATTERN.format(gatta) if gatta else None)
        conn.execute(
            "INSERT INTO grant_streams(id,gatta_id,name_is,name_en,family,format_track,stage,level,portal_url,purpose,max_amount_isk,amount_basis,payment_split,rules_json,notes,confidence,checked_at,sources_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["id"], gatta, s.get("name_is"), s.get("name_en"), s.get("family"),
             s.get("format_track"), s.get("stage"),
             None if s.get("level") is None else str(s.get("level")),
             portal, s.get("purpose"), s.get("max_amount_isk"), s.get("amount_basis"),
             s.get("payment_split"),
             json.dumps(s.get("rules", {}), ensure_ascii=False), s.get("notes"),
             conf, meta.get("checked_at"), sj),
        )
        for key, docs in (s.get("documents") or {}).items():
            level = DOC_LEVELS.get(key, key)
            for d in docs:
                conn.execute(
                    "INSERT INTO stream_documents(stream_id,requirement_level,document_text,doc_key) VALUES(?,?,?,?)",
                    (s["id"], level, d, match_doc(d)),
                )

    # grant_amounts (authoritative, from úthlutanir PDFs)
    for a in amounts:
        conn.execute(
            "INSERT INTO grant_amounts(family,format_track,year,stage_note,structure,parts_json,total_isk,quote,source,source_line,confidence) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (a.get("family"), a.get("format_track"), a.get("year"), a.get("stage_note"),
             a.get("structure"), json.dumps(a.get("parts", []), ensure_ascii=False),
             a.get("total"), a.get("quote"), a.get("source"), a.get("source_line"),
             a.get("confidence")),
        )

    # rebate
    conf, sj = check_meta("rebate", rebate.get("_meta"))
    r = rebate
    conn.execute(
        "INSERT INTO rebate(id,name_is,name_en,general_pct,general_basis,enhanced_pct,enhanced_conditions,regla_18_manuda,audit_trail,confidence,sources_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (r["id"], r.get("name_is"), r.get("name_en"),
         r["rates"].get("general_pct"), r["rates"].get("general_basis"),
         r["rates"].get("enhanced_pct"), r["rates"].get("enhanced_conditions"),
         r["producer_strategy"].get("regla_18_manuda"), r["producer_strategy"].get("audit_trail"),
         conf, sj),
    )
    for st in r.get("stages", []):
        conn.execute(
            "INSERT INTO rebate_stages(rebate_id,ord,id,name_is,description,stream_id) VALUES(?,?,?,?,?,?)",
            (r["id"], st.get("order"), st.get("id"), st.get("name_is"), st.get("description"), st.get("stream_id")),
        )

    # process
    cp = process["contract_process"]
    for st in cp.get("stages", []):
        conn.execute(
            "INSERT INTO process_stages(process_id,ord,id,name_is,condition,deadline_months,regulation_ref,submit_email) VALUES(?,?,?,?,?,?,?,?)",
            (cp["id"], st.get("order"), st.get("id"), st.get("name_is"), st.get("condition"),
             st.get("deadline_months"), st.get("regulation_ref"), st.get("submit_email")),
        )
        for item in st.get("checklist", []):
            conn.execute("INSERT INTO process_checklist(stage_id,title,description) VALUES(?,?,?)",
                         (st.get("id"), item.get("title"), item.get("description")))
        for form in st.get("forms", []):
            conn.execute("INSERT INTO process_forms(stage_id,title,format,url) VALUES(?,?,?,?)",
                         (st.get("id"), form.get("title"), form.get("format"), form.get("url")))
    dep = process["film_archive_deposit"]
    for key, url in dep.get("links", {}).items():
        conn.execute("INSERT INTO film_archive_links(deposit_id,link_key,url) VALUES(?,?,?)",
                     (dep["id"], key, url))

    # allocations: load from staged if present (ledger comes later)
    staged = ROOT / "data" / "staged" / "allocations.json"
    alloc_n = 0
    if staged.exists():
        for a in json.loads(staged.read_text(encoding="utf-8")):
            conn.execute(
                "INSERT INTO allocations(year,project_title,family,subtype,format_track,applicant,company,producer,director,writer,amount_isk,total_isk,commitment_isk,commitments_json,source_id,raw_line,confidence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("year"), a.get("project_title"), a.get("family"), a.get("subtype"),
                 a.get("format_track"), a.get("applicant"), a.get("company"),
                 a.get("producer"), a.get("director"), a.get("writer"), a.get("amount_isk"),
                 a.get("total_isk"), a.get("commitment_isk"), a.get("commitments_json"),
                 a.get("source_id"), a.get("raw_line"), a.get("confidence", "needs_verification")),
            )
            alloc_n += 1

    # ============ Zone 2: landscape entity graph (reads Zone 1; Z1 never depends on Z2) ============
    import re as _re
    from collections import defaultdict

    def _norm(t):  # title / person name norm
        t = _re.sub(r"\(.*?\)", " ", (t or "").lower())
        return _re.sub(r"\s+", " ", _re.sub(r"[^0-9a-záéíóúýþæöð]+", " ", t)).strip()

    def _cnorm(s):  # company norm (drops legal suffixes)
        s = _re.sub(r"\b(ehf|slf|sf|hf|ses)\b", " ", (s or "").lower())
        return _re.sub(r"\s+", " ", _re.sub(r"[^0-9a-záéíóúýþæöð]+", " ", s)).strip()

    def _people(s):  # split a credit field into individual names
        for part in _re.split(r"\s*[,/&]\s*|\s+og\s+", s or ""):
            n = part.strip()
            if n and "vilyrði" not in n.lower():
                yield n

    KIND = {"leikin_kvikmynd": "film", "leikid_sjonvarp": "series",
            "heimildamynd": "documentary", "stuttmynd": "short"}
    aliases = []

    # ---- companies: authoritative SÍK + allocation-derived (exact-norm link, fuzzy parked) ----
    companies = {}
    cid = [0]

    def _add_company(name, norm, **kw):
        cid[0] += 1
        companies[norm] = {"id": cid[0], "name": name, "name_norm": norm, **kw}
        return companies[norm]

    sik_path = ROOT / "data" / "staged" / "companies_producers.json"
    if sik_path.exists():
        for c in json.loads(sik_path.read_text(encoding="utf-8")):
            norm = _cnorm(c["name"])
            if norm and norm not in companies:
                _add_company(c["name"], norm, type=c.get("type"), is_sik_member=1, website=c.get("website"),
                             email=c.get("email"), phone=c.get("phone"), address=c.get("address"),
                             source="src.producers_is", confidence="verified")
    sik_norms = list(companies)
    for (raw,) in conn.execute("SELECT DISTINCT company FROM allocations WHERE company IS NOT NULL AND TRIM(company)!=''"):
        norm = _cnorm(raw)
        if not norm:
            continue
        if norm in companies:
            aliases.append(("company", raw, norm, companies[norm]["id"], "src.uthlutanir", "exact_norm", "high", "resolved"))
        else:
            ent = _add_company(raw, norm, type="production", is_sik_member=0, website=None, email=None,
                               phone=None, address=None, source="src.uthlutanir", confidence="needs_verification")
            aliases.append(("company", raw, norm, ent["id"], "src.uthlutanir", "self", "high", "resolved"))
            for sn in sik_norms:  # fuzzy suggestion to a SÍK member — NEVER auto-merged
                if sn != norm and len(sn) >= 4 and len(norm) >= 4 and (sn in norm or norm in sn):
                    aliases.append(("company", raw, norm, companies[sn]["id"], "src.uthlutanir", "fuzzy_contains", "inferred", "unresolved"))
                    break
    croll = defaultdict(lambda: {"n": 0, "isk": 0, "years": set()})
    for a in conn.execute("SELECT company, amount_isk, year FROM allocations WHERE company IS NOT NULL AND amount_isk IS NOT NULL"):
        r = croll[_cnorm(a["company"])]
        r["n"] += 1
        r["isk"] += a["amount_isk"]
        if a["year"]:
            r["years"].add(a["year"])
    for ent in companies.values():
        r = croll.get(ent["name_norm"], {"n": 0, "isk": 0, "years": set()})
        conn.execute(
            "INSERT INTO company(id,name,name_norm,type,is_sik_member,website,email,phone,address,kmi_grants_count,kmi_total_isk,kmi_years_json,source,confidence) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ent["id"], ent["name"], ent["name_norm"], ent.get("type"), ent.get("is_sik_member"),
             ent.get("website"), ent.get("email"), ent.get("phone"), ent.get("address"),
             r["n"], r["isk"], json.dumps(sorted(r["years"])), ent.get("source"), ent.get("confidence")),
        )
    company_by_norm = {n: e["id"] for n, e in companies.items()}

    # ---- titles: production catalog + every allocation project ----
    title_reg = {}     # title_norm -> title_id
    prod_dirs = []     # (title_id, director_string) from the production catalog
    allocs = list(conn.execute(
        "SELECT id, project_title, year, amount_isk, commitment_isk, family, format_track, company, director, writer, producer FROM allocations"))
    alloc_idx = [(_norm(a["project_title"]), a) for a in allocs if len(_norm(a["project_title"])) >= 3]

    for prod_staged in sorted((ROOT / "data" / "staged").glob("productions_*.json")):
        for p in json.loads(prod_staged.read_text(encoding="utf-8")):
            npn, py = _norm(p.get("title")), p.get("year")
            matches = []
            for nt, a in alloc_idx:
                exact = nt == npn
                contained = len(npn) >= 5 and (npn in nt or nt in npn)
                if not (exact or contained):
                    continue
                if py and a["year"] and not (py - 9 <= a["year"] <= py + 1):
                    continue
                matches.append({"year": a["year"], "amount_isk": a["amount_isk"] or a["commitment_isk"] or 0, "exact": exact})
            conf = "high" if any(m["exact"] for m in matches) else ("medium" if matches else "none")
            xref = "matched" if matches else ("likely_unfunded" if (py and py >= 2022) else "ledger_gap")
            cur = conn.execute(
                "INSERT INTO title(kvik_id,imdb_tconst,title,year,kind,status,director,where_shown_json,og_type,url,source,kmi_funded,kmi_alloc_count,kmi_total_isk,kmi_years_json,match_confidence,xref_status,matched_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.get("kvik_id"), p.get("imdb"), p.get("title"), py, p.get("kind"), p.get("status"), p.get("director"),
                 json.dumps(p.get("where_shown", []), ensure_ascii=False), p.get("og_type_hint"), p.get("url"), p.get("source"),
                 1 if matches else 0, len(matches), sum(m["amount_isk"] for m in matches),
                 json.dumps(sorted({m["year"] for m in matches if m["year"]})), conf, xref,
                 json.dumps(matches, ensure_ascii=False)))
            tid = cur.lastrowid
            if npn and npn not in title_reg:
                title_reg[npn] = tid
            if p.get("director"):
                prod_dirs.append((tid, p.get("director")))

    for npn, a in alloc_idx:  # every allocation project becomes a title (resolve or create)
        if npn not in title_reg:
            cur = conn.execute(
                "INSERT INTO title(title,year,kind,source,kmi_funded,match_confidence,xref_status,confidence) "
                "VALUES(?,?,?,?,1,'high','matched','needs_verification')",
                (a["project_title"], a["year"], KIND.get(a["format_track"]), "src.uthlutanir"))
            title_reg[npn] = cur.lastrowid
            aliases.append(("title", a["project_title"], npn, cur.lastrowid, "src.uthlutanir", "self", "high", "resolved"))

    # ---- award: title-resolved view of every allocation ----
    for a in allocs:
        tid = title_reg.get(_norm(a["project_title"]))
        if tid:
            conn.execute("INSERT INTO award(title_id,allocation_id,year,amount_isk,family,source) VALUES(?,?,?,?,?,?)",
                         (tid, a["id"], a["year"], a["amount_isk"] or a["commitment_isk"], a["family"], "src.uthlutanir"))

    # ---- people + title_credit + title_company ----
    people = {}
    pid = [0]

    def _person(name):
        norm = _norm(name)
        if not norm:
            return None
        if norm not in people:
            pid[0] += 1
            people[norm] = {"id": pid[0], "display": name.strip(), "norm": norm}
        return people[norm]["id"]

    credit_set, credits, tco_set, tcos = set(), [], set(), []

    def _credit(tid, name, role, src):
        p = _person(name)
        if p and (tid, p, role) not in credit_set:
            credit_set.add((tid, p, role))
            credits.append((tid, p, role, src, "needs_verification"))

    for tid, dirstr in prod_dirs:
        for n in _people(dirstr):
            _credit(tid, n, "director", "production_catalog")
    for a in allocs:
        tid = title_reg.get(_norm(a["project_title"]))
        if not tid:
            continue
        for field, role in (("director", "director"), ("writer", "writer"), ("producer", "producer")):
            for n in _people(a[field]):
                _credit(tid, n, role, "src.uthlutanir")
        if a["company"]:
            cx = company_by_norm.get(_cnorm(a["company"]))
            if cx and (tid, cx) not in tco_set:
                tco_set.add((tid, cx))
                tcos.append((tid, cx, "producer", "src.uthlutanir", "needs_verification"))

    proles, pcount = defaultdict(set), defaultdict(int)
    for tid, p, role, *_ in credits:
        proles[p].add(role)
        pcount[p] += 1
    for info in people.values():
        i = info["id"]
        conn.execute("INSERT INTO person(id,display_name,name_norm,primary_roles,credit_count,source,confidence) VALUES(?,?,?,?,?,?,?)",
                     (i, info["display"], info["norm"], ",".join(sorted(proles.get(i, []))), pcount.get(i, 0), "src.uthlutanir", "needs_verification"))
    conn.executemany("INSERT INTO title_credit(title_id,person_id,role,source,confidence) VALUES(?,?,?,?,?)", credits)
    conn.executemany("INSERT INTO title_company(title_id,company_id,role,source,confidence) VALUES(?,?,?,?,?)", tcos)
    conn.executemany("INSERT INTO alias(entity_type,raw_string,raw_norm,entity_id,source,match_method,confidence,status) VALUES(?,?,?,?,?,?,?,?)", aliases)

    # ---- B4: IMDb full-credits fold (src.imdbinfo) — Zone 2 ONLY, strong keys nconst/conmst ----
    # Folds data/raw/imdb_full/<tt>.json (full department crew + production/sales/distribution
    # companies + box-office/awards facts) onto the existing spine. Resolution is strong-key:
    # nconst/conmst dedupe; same name + different strong key stays a DISTINCT entity (never merged).
    imdb_dir = ROOT / "data" / "raw" / "imdb_full"
    imdb_files = sorted(imdb_dir.glob("tt*.json")) if imdb_dir.exists() else []
    istats = {"titles": 0, "new_people": 0, "linked_people": 0, "new_cos": 0, "linked_cos": 0}
    if imdb_files:
        title_by_tconst = {tt: tid for tt, tid in conn.execute(
            "SELECT imdb_tconst, id FROM title WHERE imdb_tconst LIKE 'tt%'")}
        pname_to_id = {info["norm"]: info["id"] for info in people.values()}
        pnconst_to_id, pid_counter = {}, [pid[0]]
        cname_to_id, cconmst_to_id, cid_counter = dict(company_by_norm), {}, [cid[0]]
        imdb_credits, imdb_tcos = [], []
        icredit_set, itco_set = set(credit_set), set(tco_set)
        ROLE_ALIAS = {"actor": "cast", "actress": "cast"}
        CO_TYPE = {"production": "production", "distribution": "distribution",
                   "sales": "sales", "specialEffects": "vfx", "miscellaneous": "misc"}

        def _money(s):
            d = _re.sub(r"[^\d]", "", str(s or ""))
            return int(d) if d else None

        def _imdb_person(nconst, name):
            norm = _norm(name)
            if nconst and nconst in pnconst_to_id:
                return pnconst_to_id[nconst]
            if norm and norm in pname_to_id:                       # exact-name link to existing person
                p = pname_to_id[norm]
                if nconst:
                    pnconst_to_id[nconst] = p
                    conn.execute("UPDATE person SET imdb_nconst=COALESCE(imdb_nconst,?) WHERE id=?", (nconst, p))
                    istats["linked_people"] += 1
                return p
            if not (norm or nconst):
                return None
            pid_counter[0] += 1
            p = pid_counter[0]
            if norm:
                pname_to_id[norm] = p
            if nconst:
                pnconst_to_id[nconst] = p
            conn.execute("INSERT INTO person(id,display_name,name_norm,imdb_nconst,region,source,confidence) "
                         "VALUES(?,?,?,?,NULL,'src.imdbinfo','verified')",
                         (p, (name or "").strip() or None, norm, nconst))
            istats["new_people"] += 1
            return p

        def _imdb_company(conmst, name, ctype):
            norm = _cnorm(name)
            if conmst and conmst in cconmst_to_id:
                return cconmst_to_id[conmst]
            if norm and norm in cname_to_id:
                cx = cname_to_id[norm]
                if conmst:
                    cconmst_to_id[conmst] = cx
                    conn.execute("UPDATE company SET imdb_conmst=COALESCE(imdb_conmst,?) WHERE id=?", (conmst, cx))
                    istats["linked_cos"] += 1
                return cx
            if not (norm or conmst):
                return None
            cid_counter[0] += 1
            cx = cid_counter[0]
            if norm:
                cname_to_id[norm] = cx
            if conmst:
                cconmst_to_id[conmst] = cx
            conn.execute("INSERT INTO company(id,name,name_norm,type,is_sik_member,imdb_conmst,source,confidence) "
                         "VALUES(?,?,?,?,0,?,'src.imdbinfo','verified')", (cx, name, norm, ctype, conmst))
            istats["new_cos"] += 1
            return cx

        for f in imdb_files:
            rec = json.loads(f.read_text(encoding="utf-8"))
            tid = title_by_tconst.get(rec.get("imdb_tconst"))
            if not tid:
                continue
            istats["titles"] += 1
            aw = rec.get("awards") or {}
            conn.execute(
                "UPDATE title SET imdb_rating=?, imdb_votes=?, imdb_award_wins=?, imdb_award_noms=?, "
                "worldwide_gross_usd=?, production_budget=?, imdb_genres_json=?, imdb_countries_json=?, "
                "imdb_akas_json=?, imdb_enriched=1 WHERE id=?",
                (rec.get("rating"), rec.get("votes"), aw.get("wins"), aw.get("nominations"),
                 _money(rec.get("worldwide_gross")), rec.get("production_budget"),
                 json.dumps(rec.get("genres") or [], ensure_ascii=False),
                 json.dumps(rec.get("countries") or [], ensure_ascii=False),
                 json.dumps(rec.get("title_akas") or [], ensure_ascii=False), tid))
            for cat, items in (rec.get("crew") or {}).items():
                role = ROLE_ALIAS.get(cat, cat)
                for it in items:
                    p = _imdb_person(it.get("nconst"), it.get("name"))
                    if p and (tid, p, role) not in icredit_set:
                        icredit_set.add((tid, p, role))
                        imdb_credits.append((tid, p, role, it.get("job"), "src.imdbinfo", "verified"))
            for crole, items in (rec.get("companies") or {}).items():
                for it in items:
                    cx = _imdb_company(it.get("conmst"), it.get("name"), CO_TYPE.get(crole, "misc"))
                    if cx and (tid, cx) not in itco_set:
                        itco_set.add((tid, cx))
                        imdb_tcos.append((tid, cx, crole, "src.imdbinfo", "verified"))

        conn.executemany("INSERT INTO title_credit(title_id,person_id,role,job,source,confidence) VALUES(?,?,?,?,?,?)", imdb_credits)
        conn.executemany("INSERT INTO title_company(title_id,company_id,role,source,confidence) VALUES(?,?,?,?,?)", imdb_tcos)
        # recompute person rollups over úthlutanir + IMDb credits
        proles2, pcount2 = defaultdict(set), defaultdict(int)
        for row in credits + imdb_credits:
            proles2[row[1]].add(row[2])
            pcount2[row[1]] += 1
        for i, n in pcount2.items():
            conn.execute("UPDATE person SET credit_count=?, primary_roles=? WHERE id=?",
                         (n, ",".join(sorted(proles2[i])), i))
        istats["credits"] = len(imdb_credits)
        istats["tcos"] = len(imdb_tcos)
        print(f"  IMDb fold: {istats['titles']} titles · +{istats['credits']} credits "
              f"(+{istats['new_people']} new / {istats['linked_people']} linked people) · "
              f"+{istats['tcos']} company edges (+{istats['new_cos']} new / {istats['linked_cos']} linked cos)")

    conn.commit()

    def count(t: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    print(f"Built {DB_PATH.relative_to(ROOT)}")
    matched = conn.execute("SELECT COUNT(*) FROM stream_documents WHERE doc_key IS NOT NULL").fetchone()[0]
    print(f"  sources={count('sources')}  families={count('grant_families')}  "
          f"streams={count('grant_streams')}  stream_documents={count('stream_documents')} (doc_key matched={matched})")
    print(f"  documents={count('documents')}  criteria={count('criteria')}")
    print(f"  rebate_stages={count('rebate_stages')}  process_stages={count('process_stages')}  "
          f"process_checklist={count('process_checklist')}  grant_amounts={count('grant_amounts')}  "
          f"allocations={count('allocations')}")
    if count("title"):
        funded = conn.execute("SELECT COUNT(*) FROM title WHERE kmi_funded=1").fetchone()[0]
        print(f"  title={count('title')} (catalog-matched={funded})  award={count('award')}")
        print(f"  person={count('person')}  title_credit={count('title_credit')}  title_company={count('title_company')}")
    if count("company"):
        sik = conn.execute("SELECT COUNT(*) FROM company WHERE is_sik_member=1").fetchone()[0]
        unres = conn.execute("SELECT COUNT(*) FROM alias WHERE status='unresolved'").fetchone()[0]
        print(f"  company={count('company')} (SÍK={sik})  alias={count('alias')} (unresolved fuzzy={unres})")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings[:30]:
            print("  WARN", w)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
