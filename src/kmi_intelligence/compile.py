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
import re
import sqlite3
import sys
from pathlib import Path

from . import log_event

ROOT = Path(__file__).resolve().parents[2]
CURATED = ROOT / "data" / "curated"
BUILD = ROOT / "build"

# Clean grant-label contamination out of name/company fields parsed from the úthlutanir PDFs.
# Pattern A (recoverable): a real name/company with a trailing label — "Reykjavík Films Styrkur",
# "Grímar Jónsson Vilyrði", "Wonderfilms (vilyrði skilað)". Pattern B (garbage): a whole mis-parsed
# travel/festival row whose "name" is a grant-purpose description — "Ferðastyrkur á Nordisk
# Panorama-…", "rarstyrkur 150.000". A returns the clean name; B returns None (no entity made).
_TRAIL_LABELS = {"styrkur", "styrkir", "vilyrði", "vilyrdi"}
_GARBAGE = re.compile(
    r"ferðastyrk|ferdastyrk|þátttökustyrk|thatttoku|þátttöku í|vinnusto|vinnusmi|handritasmi|"
    r"handritavinnusmi|ráðstefn|radstefn|nordisk panorama|\bynpc\b|flugmið|endurgreidd|styrkur til|"
    r"styrkut til|\d", re.I)


def _clean_entity_field(s):
    if not s:
        return s
    v = re.sub(r"\([^)]*(?:vilyr[ðd]i|skila[ðd])[^)]*\)", " ", s, flags=re.I)  # drop "(vilyrði skilað)"
    v = re.sub(r"\s+", " ", v).strip()
    toks = v.split()
    while toks and re.sub(r"[^0-9a-záéíóúýþæöð]", "", toks[-1].lower()) in _TRAIL_LABELS:
        toks.pop()  # strip trailing Styrkur/Vilyrði (possibly repeated)
    v = " ".join(toks).strip(" -–/.,")
    if not v or _GARBAGE.search(v):
        return None  # Pattern B garbage → no entity
    return v
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
    kvik_person_id TEXT, region TEXT DEFAULT 'IS', primary_roles TEXT,
    credit_count INTEGER,                 -- CATALOG-SCOPED: credits within our ~919-title KMÍ catalog
                                          -- only. NOT a career count; do NOT read as a debut signal.
    career_first_feature_year INTEGER,    -- REAL IMDb career: earliest feature (kind=movie) across roles
    career_json TEXT,                     -- per-role {first_feature_year,first_feature_tconst,feature_count}
    layer TEXT,                           -- 'creative' (holds any crew role) or 'cast' (acting only) — actors kept separate
    source TEXT, confidence TEXT
);

CREATE TABLE title_credit (title_id INTEGER, person_id INTEGER, role TEXT, job TEXT, source TEXT, confidence TEXT);

-- collaboration graph: who has worked with whom, and how many times (repeat collaborations, shared>=2).
-- edge_class lets the node map keep actors separate: 'creative' (crew↔crew), 'cast' (actor↔actor), 'mixed'.
CREATE TABLE person_collab (a_id INTEGER, b_id INTEGER, shared INTEGER, edge_class TEXT, titles_json TEXT);
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

-- Zone 3 — CORPUS + landscape facts (reads Zone 1/2, NEVER written-to by them; grant tools never join these)
CREATE TABLE corpus_article (
    id INTEGER PRIMARY KEY, source TEXT, ext_id INTEGER, date TEXT, year INTEGER,
    url TEXT, slug TEXT, title TEXT, categories_json TEXT, primary_category TEXT,
    tags_json TEXT, body_chars INTEGER, body TEXT
);
CREATE TABLE corpus_mention (
    article_id INTEGER, entity_type TEXT, entity_id INTEGER, raw_string TEXT,
    method TEXT, confidence TEXT
);
CREATE TABLE lx_admissions (
    id INTEGER PRIMARY KEY, title_id INTEGER, film TEXT, date TEXT, year INTEGER, scope TEXT,
    week_admissions INTEGER, total_admissions INTEGER, gross_isk INTEGER, weeks_in_release TEXT,
    article_id INTEGER, source TEXT, confidence TEXT
);
CREATE TABLE lx_viewership (
    id INTEGER PRIMARY KEY, title_id INTEGER, title_text TEXT, channel TEXT, date TEXT, year INTEGER,
    viewers INTEGER, rating_pct REAL, episodes INTEGER, article_id INTEGER, source TEXT, confidence TEXT
);
CREATE TABLE lx_review (
    id INTEGER PRIMARY KEY, title_id INTEGER, subject TEXT, outlet TEXT, date TEXT, year INTEGER,
    headline TEXT, article_id INTEGER, source TEXT, confidence TEXT
);
CREATE TABLE lx_award (
    id INTEGER PRIMARY KEY, title_id INTEGER, person_id INTEGER, subject TEXT, result TEXT,
    award_hint TEXT, date TEXT, year INTEGER, headline TEXT, article_id INTEGER, source TEXT, confidence TEXT
);

-- reference: Icelandic↔English domain lexicon (pure reference, zone-agnostic)
CREATE TABLE lexicon (
    id INTEGER PRIMARY KEY, term_is TEXT, term_en TEXT, category TEXT, literal TEXT, note TEXT, src TEXT
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
CREATE INDEX idx_lx_adm_title ON lx_admissions(title_id);
CREATE INDEX idx_lx_view_title ON lx_viewership(title_id);
CREATE INDEX idx_lx_review_title ON lx_review(title_id);
CREATE INDEX idx_lx_award_title ON lx_award(title_id);
CREATE INDEX idx_corpus_mention ON corpus_mention(entity_type, entity_id);
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

    # allocations: load from staged if present (ledger comes later). allocations.json is the modern
    # 2021–24 PDF parse; allocations_archive.json is the pre-2021 set recovered from the Internet
    # Archive (ingest/uthlutanir_archive.py) — same shape, carries source_id ...wayback. Both fold in
    # so the ledger reaches back to ~2015; a pre-2021 film is no longer "before our window" by accident.
    alloc_n = 0
    for staged in (ROOT / "data" / "staged" / "allocations.json",
                   ROOT / "data" / "staged" / "allocations_archive.json"):
        if not staged.exists():
            continue
        for a in json.loads(staged.read_text(encoding="utf-8")):
            conn.execute(
                "INSERT INTO allocations(year,project_title,family,subtype,format_track,applicant,company,producer,director,writer,amount_isk,total_isk,commitment_isk,commitments_json,source_id,raw_line,confidence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("year"), a.get("project_title"), a.get("family"), a.get("subtype"),
                 a.get("format_track"), _clean_entity_field(a.get("applicant")), _clean_entity_field(a.get("company")),
                 _clean_entity_field(a.get("producer")), _clean_entity_field(a.get("director")),
                 _clean_entity_field(a.get("writer")), a.get("amount_isk"),
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

    def _clean_title(raw):
        """(canonical, [former_titles]). Pulls '(áður X)' working-title changes out as data, not noise:
        a project's title evolution (e.g. 'Love Odyssey' -> 'Eternal'). Handles a truncated '(áður'."""
        t = (raw or "").strip()
        formers = []
        m = _re.search(r"\s*\(\s*áður:?\s*(.*)$", t, _re.I)
        if m:
            t = t[:m.start()].strip()
            former = _re.split(r"\)", m.group(1))[0].strip()   # former name = up to the closing paren
            if len(former) > 1:
                formers.append(former)
        return t.strip(" -–—"), formers

    def _is_admin_blob(raw):
        """An 'annað' grant whose whole description landed in project_title — travel/festival/premiere/
        screening/operating support (e.g. 'Noumena ehf. Ferðastyrkur: Þátttaka í Nordisk Panorama 2024',
        'Berdreymi Join Motion Pictures ehf. Berlinale'). NOT a production. A company suffix mid-string
        ('… ehf. …') or any of these grant keywords marks it; the real film (if any) exists separately."""
        low = (raw or "").lower()
        return len(raw or "") > 45 and bool(_re.search(
            r"ferðastyrk|þátttak|styrkur til |vinnustof|vinnusmið|ferð og þátttök|þáttt[:.]| lab\b|"
            r"workshop|festival|kvikmyndahát|frumsýning|sýningarstyrk|green producers|kolefni|"
            r"óskarsverðlaun|starfsemi|\behf\.|\bohf\.|\bslf\.|\bses\b", low))

    # human-confirmed merges (from the review UI) collapse duplicates at build time.
    # Format: {"company": {merges:[{keep,drop,...}]}, "person": {...}}  (old flat = company-only).
    merges_path = ROOT / "data" / "curated" / "entity_merges.json"
    _merge_redirect, _merge_log = {}, []        # company: norm -> keep_norm, + alias log
    _person_redirect, _person_merge_log = {}, []  # person:  norm -> keep_norm, + alias log
    _title_redirect, _title_merge_log = {}, []  # title:   norm -> keep_norm, + alias log
    if merges_path.exists():
        _md = json.loads(merges_path.read_text(encoding="utf-8"))
        for m in (_md.get("company", {}).get("merges", []) or _md.get("merges", [])):
            for drop in m.get("drop", []):
                _merge_redirect[drop] = m["keep"]
                _merge_log.append((m["keep"], drop, m.get("drop_name", drop), m.get("reason", "")))
        for m in _md.get("person", {}).get("merges", []):
            for drop in m.get("drop", []):
                _person_redirect[drop] = m["keep"]
                _person_merge_log.append((m["keep"], drop, m.get("drop_name", drop), m.get("keep_name", m["keep"])))
        # title merges: a project that changed name (working title → final) is ONE title, never forked.
        # The dropped (former) name is preserved as an alias DATA POINT (surfaced as "einnig þekkt sem").
        for m in _md.get("title", {}).get("merges", []):
            for drop in m.get("drop", []):
                _title_redirect[drop] = m["keep"]
                _title_merge_log.append((m["keep"], drop, m.get("drop_name", drop), m.get("keep_name", m["keep"])))

    def _flatten(rd):  # follow chains A->B->C so every drop resolves to the FINAL canonical
        for k in list(rd):
            seen, v = {k}, rd[k]
            while v in rd and v not in seen:
                seen.add(v)
                v = rd[v]
            rd[k] = v
    _flatten(_merge_redirect)
    _flatten(_person_redirect)
    _flatten(_title_redirect)
    _title_keep_display = {kn: kname for kn, _, _, kname in _title_merge_log}  # canonical norm -> display

    def _cnorm(s):  # company norm (drops legal suffixes); applies confirmed merges
        s = _re.sub(r"\b(ehf|slf|sf|hf|ses)\b", " ", (s or "").lower())
        base = _re.sub(r"\s+", " ", _re.sub(r"[^0-9a-záéíóúýþæöð]+", " ", s)).strip()
        return _merge_redirect.get(base, base)

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
    # log confirmed merges (the dropped name now resolves to the canonical company)
    for keep_norm, drop_norm, drop_name, reason in _merge_log:
        cid_keep = company_by_norm.get(keep_norm)
        if cid_keep:
            aliases.append(("company", drop_name, drop_norm, cid_keep, "entity_merges",
                            "manual_merge", "verified", "resolved"))

    # ---- titles: production catalog + every allocation project ----
    title_reg = {}     # title_norm (canonical) -> title_id
    prod_dirs = []     # (title_id, director_string) from the production catalog

    def _tnorm(s):     # title norm + confirmed title merges (a renamed/variant title → its canonical)
        n = _norm(s)
        return _title_redirect.get(n, n)

    allocs = list(conn.execute(
        "SELECT id, project_title, year, amount_isk, commitment_isk, family, format_track, company, director, writer, producer FROM allocations"))
    alloc_idx = [(_tnorm(a["project_title"]), _norm(a["project_title"]), a)
                 for a in allocs if len(_norm(a["project_title"])) >= 3]

    # resolved IMDb links (from ingest/imdb_resolve.py) backfill tconsts onto catalog titles
    links_path = ROOT / "data" / "curated" / "imdb_links.json"
    imdb_link = {}            # (title_norm, year) -> tconst   +  title_norm -> tconst (fallback)
    if links_path.exists():
        for l in json.loads(links_path.read_text(encoding="utf-8")):
            tt = l.get("imdb_tconst")
            if tt:
                imdb_link[(l.get("title_norm"), l.get("year"))] = tt
                imdb_link.setdefault(l.get("title_norm"), tt)

    for prod_staged in sorted((ROOT / "data" / "staged").glob("productions_*.json")):
        for p in json.loads(prod_staged.read_text(encoding="utf-8")):
            npn, py = _tnorm(p.get("title")), p.get("year")
            tconst = p.get("imdb") or imdb_link.get((npn, py)) or imdb_link.get(npn)
            matches = []
            for nt, _raw, a in alloc_idx:
                exact = nt == npn
                contained = len(npn) >= 5 and (npn in nt or nt in npn)
                if not (exact or contained):
                    continue
                if py and a["year"] and not (py - 9 <= a["year"] <= py + 1):
                    continue
                matches.append({"year": a["year"], "amount_isk": a["amount_isk"] or a["commitment_isk"] or 0, "exact": exact})
            conf = "high" if any(m["exact"] for m in matches) else ("medium" if matches else "none")
            # Funding status is about what KMÍ's ledger RECORDS, never an assertion that a film was
            # "unfunded". Our allocation data covers 2021–24 only: a title in-window with no match has
            # "no record" (could be a match miss or a stream we lack); a pre-2021 title is simply
            # before our window — funding status genuinely UNKNOWN (older script grants existed).
            xref = "matched" if matches else ("no_record_in_window" if (py and py >= 2021) else "before_window")
            ptitle, pformers = _clean_title(p.get("title"))
            ptitle = _title_keep_display.get(npn, ptitle)   # if merged, show the canonical name
            cur = conn.execute(
                "INSERT INTO title(kvik_id,imdb_tconst,title,year,kind,status,director,where_shown_json,og_type,url,source,kmi_funded,kmi_alloc_count,kmi_total_isk,kmi_years_json,match_confidence,xref_status,matched_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.get("kvik_id"), tconst, ptitle, py, p.get("kind"), p.get("status"), p.get("director"),
                 json.dumps(p.get("where_shown", []), ensure_ascii=False), p.get("og_type_hint"), p.get("url"), p.get("source"),
                 1 if matches else 0, len(matches), sum(m["amount_isk"] for m in matches),
                 json.dumps(sorted({m["year"] for m in matches if m["year"]})), conf, xref,
                 json.dumps(matches, ensure_ascii=False)))
            tid = cur.lastrowid
            if npn and npn not in title_reg:
                title_reg[npn] = tid
            for fmr in pformers:                 # working-title history: former name + when (the title's year)
                aliases.append(("title", fmr, _norm(fmr), tid, f"{p.get('source')}#{py}", "former_title", "high", "resolved"))
            if p.get("director"):
                prod_dirs.append((tid, p.get("director")))

    for npn, raw, a in alloc_idx:  # most allocation projects become a title (resolve or create)
        if npn in title_reg:
            # Resolves to an existing title. If this allocation's own name differs from the canonical
            # (a confirmed rename redirected it here), preserve that name as a dated alias DATA POINT —
            # the title's funding history under its former name, NOT a forked duplicate.
            if raw != npn:
                aliases.append(("title", a["project_title"], raw, title_reg[npn],
                                f"src.uthlutanir#{a['year']}", "renamed_to", "verified", "resolved"))
            continue
        # Travel/participation/misc 'annað' grants are NOT productions — their whole description landed
        # in project_title. Keep them as allocation DATA (queryable funding history) but don't mint a
        # garbled film title. The allocation row is untouched; we just skip the title/award edge.
        if a["family"] == "annad" and _is_admin_blob(a["project_title"]):
            continue
        canon, formers = _clean_title(a["project_title"])
        canon = _title_keep_display.get(npn, canon)   # if this norm is a confirmed canonical, use its name
        cur = conn.execute(
            "INSERT INTO title(title,year,kind,source,kmi_funded,match_confidence,xref_status,confidence) "
            "VALUES(?,?,?,?,1,'high','matched','needs_verification')",
            (canon, a["year"], KIND.get(a["format_track"]), "src.uthlutanir"))
        title_reg[npn] = cur.lastrowid
        aliases.append(("title", a["project_title"], raw, cur.lastrowid, "src.uthlutanir", "self", "high", "resolved"))
        for fmr in formers:                  # working-title history: former name + when (allocation year)
            aliases.append(("title", fmr, _norm(fmr), cur.lastrowid, f"src.uthlutanir#{a['year']}", "former_title", "high", "resolved"))

    # ---- award: title-resolved view of every allocation ----
    for a in allocs:
        tid = title_reg.get(_tnorm(a["project_title"]))
        if tid:
            conn.execute("INSERT INTO award(title_id,allocation_id,year,amount_isk,family,source) VALUES(?,?,?,?,?,?)",
                         (tid, a["id"], a["year"], a["amount_isk"] or a["commitment_isk"], a["family"], "src.uthlutanir"))

    # ---- people + title_credit + title_company ----
    people = {}
    pid = [0]
    _keep_display = {kn: kname for kn, _, _, kname in _person_merge_log}  # canonical norm -> display

    def _person(name):
        norm = _person_redirect.get(_norm(name), _norm(name))  # apply confirmed person merges
        if not norm:
            return None
        if norm not in people:
            pid[0] += 1
            people[norm] = {"id": pid[0], "display": _keep_display.get(norm, name.strip()), "norm": norm}
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
        tid = title_reg.get(_tnorm(a["project_title"]))
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
    # log confirmed person merges (dropped name now resolves to the canonical person)
    for keep_norm, drop_norm, drop_name, _ in _person_merge_log:
        if keep_norm in people:
            aliases.append(("person", drop_name, drop_norm, people[keep_norm]["id"], "entity_merges",
                            "manual_merge", "verified", "resolved"))
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
            norm = _person_redirect.get(_norm(name), _norm(name))  # honor confirmed person merges
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

    # ---- careers fold: REAL IMDb career first-feature (from ingest/imdb.py `careers`) ----
    # Person-keyed filmographies -> career_first_feature_year (overall) + career_json (per role).
    # This is the truthful "when did they actually start" signal; the catalog-scoped credit_count
    # cannot answer it (a visiting DOP reads as credit_count=1). LOCAL-only IMDb data, never exported.
    cdir = ROOT / "data" / "raw" / "imdb_careers"
    if cdir.exists():
        folded = 0
        for f in cdir.glob("nm*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:                                                 # noqa: BLE001
                continue
            roles = rec.get("roles") or {}
            if not roles:
                continue
            years = [v["first_feature_year"] for v in roles.values() if v.get("first_feature_year")]
            first = min(years) if years else None
            folded += conn.execute(
                "UPDATE person SET career_first_feature_year=?, career_json=? WHERE imdb_nconst=?",
                (first, json.dumps(roles, ensure_ascii=False), rec.get("nconst"))).rowcount
        print(f"  careers fold: {folded} people given a real career first-feature year")

    # ---- director backfill: a missing title.director is a GAP, not "no director". Fill it from the
    # director CREDIT where we have one (IMDb/úthlutanir); titles with no director credit at all stay
    # NULL = honestly unknown (the app renders that as "óþekkt", never "no director").
    filled = conn.execute(
        "UPDATE title SET director = ("
        "  SELECT p.display_name FROM title_credit tc JOIN person p ON p.id = tc.person_id "
        "  WHERE tc.title_id = title.id AND tc.role = 'director' "
        "  ORDER BY p.credit_count DESC LIMIT 1) "
        "WHERE (director IS NULL OR director = '') "
        "AND EXISTS (SELECT 1 FROM title_credit tc WHERE tc.title_id = title.id AND tc.role = 'director')"
    ).rowcount
    print(f"  director backfill: {filled} titles given a director from credits (rest remain unknown)")

    # ---- collaboration graph: who has worked with whom, how many times (node connection map) ----
    # Each person is layered by their MOST-FREQUENT department so the node map can keep the functional
    # groups separate: creative (authorship/art) · tech (craft) · production (business) · cast (actors).
    # 'flagged' is reserved for mislinked nconsts (set by the person_credits fold). Edges = repeat
    # collaborations (shared>=2); 'thanks' credits are not collaborations and are ignored.
    from collections import Counter
    from itertools import combinations
    ROLE_LAYER = {
        "cast": "cast",
        "director": "creative", "writer": "creative", "composer": "creative", "production_designer": "creative",
        "art_director": "creative", "costume_designer": "creative", "set_decorator": "creative",
        "music_department": "creative", "art_department": "creative", "animation_department": "creative",
        "cinematographer": "tech", "camera_department": "tech", "sound_department": "tech", "editor": "tech",
        "editorial_department": "tech", "visual_effects": "tech", "special_effects": "tech",
        "make_up_department": "tech", "costume_department": "tech", "script_department": "tech",
        "stunts": "tech", "transportation_department": "tech",
        "producer": "production", "production_manager": "production", "production_department": "production",
        "assistant_director": "production", "location_management": "production",
        "casting_department": "production", "casting_director": "production", "miscellaneous": "production",
    }  # "thanks" intentionally absent → ignored
    _PRIORITY = ("creative", "production", "tech", "cast")     # tie-break: artistic identity first
    title_people, person_counts = defaultdict(set), defaultdict(Counter)
    for tid, pid, role in conn.execute("SELECT title_id, person_id, role FROM title_credit"):
        lyr = ROLE_LAYER.get(role)
        if not lyr:
            continue
        person_counts[pid][lyr] += 1
        title_people[tid].add(pid)
    person_layer = {pid: max(cnt, key=lambda k: (cnt[k], -_PRIORITY.index(k)))
                    for pid, cnt in person_counts.items()}
    for pid, layer in person_layer.items():
        conn.execute("UPDATE person SET layer=? WHERE id=?", (layer, pid))
    pair_titles = defaultdict(list)
    for tid, people in title_people.items():
        for a, b in combinations(sorted(people), 2):
            pair_titles[(a, b)].append(tid)
    edges = []
    for (a, b), tids in pair_titles.items():
        if len(tids) < 2:                      # keep REPEAT collaborations (worked together >1×)
            continue
        la, lb = person_layer[a], person_layer[b]
        edges.append((a, b, len(tids), la if la == lb else "mixed", json.dumps(tids[:40])))
    conn.executemany("INSERT INTO person_collab(a_id,b_id,shared,edge_class,titles_json) VALUES(?,?,?,?,?)", edges)
    _pl, _ec = Counter(person_layer.values()), Counter(e[3] for e in edges)
    print(f"  collaboration graph: {len(edges)} repeat-collab edges over {len(person_layer)} people | "
          f"layers {dict(_pl)} | edges {dict(_ec)}")

    # ---- Zone 3: Klapptré CORPUS + landscape facts (isolated; reads Zone 1/2 only) ----
    kdir = ROOT / "data" / "raw" / "klapptre"
    if kdir.exists() and any(kdir.glob("*.json")):
        from .ingest import klapptre as kx  # lazy: core build never depends on Zone 3
        from .ingest.textclean import to_text
        kcats = kx.load_categories()  # full id->name map (all categories on a KMI_CATS=all mirror)
        t_by_norm, p_by_norm = {}, {}
        for tid, nm in conn.execute("SELECT id, title FROM title"):
            n = _norm(nm)
            if n:
                t_by_norm.setdefault(n, tid)
        for pid_, nm in conn.execute("SELECT id, display_name FROM person"):
            n = _norm(nm)
            if n:
                p_by_norm.setdefault(n, pid_)

        def _res_title(s):
            n = _norm(s)
            if not n:
                return None
            if n in t_by_norm:
                return t_by_norm[n]
            if len(n) >= 5:
                for tn, tid in t_by_norm.items():
                    if len(tn) >= 5 and (n == tn or n in tn or tn in n):
                        return tid
            return None

        z3 = defaultdict(int)
        ids = {"a": 0, "adm": 0, "view": 0, "rev": 0, "awd": 0}
        mentions = []

        def _mention(art, etype, eid, raw):
            if eid:
                mentions.append((art, etype, eid, raw, "klapptre", "needs_verification"))
                z3["mentions"] += 1

        for a in kx.iter_articles():
            cats = set(a["cats"])
            date = a["date"]
            yr = int(date[:4]) if date[:4].isdigit() else None
            prim = next((kcats[c] for c in a["cats"] if c in kcats), None)
            ids["a"] += 1
            art = ids["a"]
            body = to_text(a["html"])
            conn.execute(
                "INSERT INTO corpus_article(id,source,ext_id,date,year,url,slug,title,categories_json,primary_category,tags_json,body_chars,body) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (art, "src.klapptre", a["id"], date, yr, a["link"], a["slug"], a["title"],
                 json.dumps(a["cats"]), prim, json.dumps(a["tags"]), len(body), body))
            z3["articles"] += 1
            if kx.CAT["adsokn"] in cats:
                scope = "WW" if _re.search(r"heimsv[ií]su|alþjóð|internationa", a["title"].lower()) else "IS"
                for r in kx.parse_admissions(a["html"]):
                    tid = _res_title(r["film"])
                    ids["adm"] += 1
                    conn.execute(
                        "INSERT INTO lx_admissions(id,title_id,film,date,year,scope,week_admissions,total_admissions,gross_isk,weeks_in_release,article_id,source,confidence) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ids["adm"], tid, r["film"], date, yr, scope, r["week_admissions"], r["total_admissions"],
                         r["gross_isk"], r["weeks_in_release"], art, "src.klapptre", "needs_verification"))
                    _mention(art, "title", tid, r["film"])
                    z3["admissions"] += 1
            if kx.CAT["ahorf"] in cats:
                for r in kx.parse_viewership(a["html"]):
                    tid = _res_title(r["title"])
                    ids["view"] += 1
                    conn.execute(
                        "INSERT INTO lx_viewership(id,title_id,title_text,channel,date,year,viewers,rating_pct,episodes,article_id,source,confidence) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ids["view"], tid, r["title"], r["channel"], date, yr, r["viewers"],
                         r["rating_pct"], r["episodes"], art, "src.klapptre", "needs_verification"))
                    _mention(art, "title", tid, r["title"])
                    z3["viewership"] += 1
            if kx.CAT["review"] in cats:
                subj = next((s for s in kx.headline_subjects(a["title"]) if _res_title(s)), None)
                tid = _res_title(subj) if subj else None
                ids["rev"] += 1
                conn.execute(
                    "INSERT INTO lx_review(id,title_id,subject,outlet,date,year,headline,article_id,source,confidence) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (ids["rev"], tid, subj, kx.review_outlet(a["title"]), date, yr, a["title"],
                     art, "src.klapptre", "needs_verification"))
                _mention(art, "title", tid, subj or a["title"])
                z3["reviews"] += 1
            if kx.CAT["award"] in cats or kx.CAT["nomination"] in cats:
                result = "win" if kx.CAT["award"] in cats else "nomination"
                tid = pid_ = None
                subj = next((s for s in kx.headline_subjects(a["title"]) if _res_title(s)), None)
                if subj:
                    tid = _res_title(subj)
                else:
                    for s in kx.name_candidates(a["title"]):
                        if _norm(s) in p_by_norm:
                            pid_, subj = p_by_norm[_norm(s)], s
                            break
                ids["awd"] += 1
                conn.execute(
                    "INSERT INTO lx_award(id,title_id,person_id,subject,result,award_hint,date,year,headline,article_id,source,confidence) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ids["awd"], tid, pid_, subj, result, kx.award_hint(a["title"]), date, yr,
                     a["title"], art, "src.klapptre", "needs_verification"))
                _mention(art, "title", tid, subj or a["title"])
                _mention(art, "person", pid_, subj or a["title"])
                z3["awards"] += 1

        print(f"  Zone 3 (Klapptré): {z3['articles']} articles · {z3['admissions']} admissions · "
              f"{z3['viewership']} viewership · {z3['reviews']} reviews · {z3['awards']} awards · "
              f"{z3['mentions']} mentions")

        # ---- KMÍ sitemap: news/culture corpus + áhorf viewership facts (src.kmi_sitemap_mirror) ----
        sdir = ROOT / "data" / "raw" / "site"
        if sdir.exists() and any(sdir.glob("*.html")):
            from .ingest import kmi_site as ksite
            SECT = {"ahorf": "Áhorf", "frettir": "Fréttir", "kvikmyndamenning": "Kvikmyndamenning",
                    "um": "Um KMÍ", "kvikmyndagerd": "Kvikmyndagerð", "other": "KMÍ"}
            kp = kv = 0
            for p in ksite.iter_pages():
                ids["a"] += 1
                art = ids["a"]
                conn.execute(
                    "INSERT INTO corpus_article(id,source,ext_id,date,year,url,slug,title,categories_json,primary_category,tags_json,body_chars,body) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (art, "src.kmi_sitemap_mirror", None, p["date"], p["year"], None, p["name"], p["title"],
                     json.dumps([p["section"]]), SECT.get(p["section"], p["section"]), json.dumps([]), len(p["text"]), p["text"]))
                kp += 1
                if p["section"] == "ahorf":
                    ym = _re.search(r"\b(20\d\d)\b", p["title"])          # CONTENT year (title), not publish
                    vyear = int(ym.group(1)) if ym else p["year"]
                    for r in ksite.parse_viewership(p["main_html"]):
                        t = _re.sub(r"\*+$", "", r["title"] or "").strip()  # "Brot**" -> "Brot"
                        if not t or t.startswith("*") or "meðaláhorf" in t.lower() or len(t) > 60:
                            continue                                       # footnote / junk row
                        tid = _res_title(t)
                        ids["view"] += 1
                        conn.execute(
                            "INSERT INTO lx_viewership(id,title_id,title_text,channel,date,year,viewers,rating_pct,episodes,article_id,source,confidence) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ids["view"], tid, t, r["channel"], p["date"], vyear, r["viewers"],
                             r["rating_pct"], r["episodes"], art, "src.kmi_sitemap_mirror", "verified"))
                        _mention(art, "title", tid, t)
                        kv += 1
            print(f"  Zone 3 (KMÍ site): {kp} pages → corpus + {kv} áhorf viewership rows")

        conn.executemany(
            "INSERT INTO corpus_mention(article_id,entity_type,entity_id,raw_string,method,confidence) VALUES(?,?,?,?,?,?)",
            mentions)

    # ---- reference: Icelandic↔English domain lexicon ----
    lex_path = ROOT / "data" / "curated" / "lexicon.json"
    if lex_path.exists():
        lex = json.loads(lex_path.read_text(encoding="utf-8")).get("terms", [])
        conn.executemany(
            "INSERT INTO lexicon(term_is,term_en,category,literal,note,src) VALUES(?,?,?,?,?,?)",
            [(t.get("is"), t.get("en"), t.get("category"), t.get("literal"), t.get("note"), t.get("src"))
             for t in lex])
        print(f"  lexicon: {len(lex)} terms")

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
    if count("title"):
        log_event("build", allocations=count("allocations"), titles=count("title"),
                  people=count("person"), credits=count("title_credit"), companies=count("company"),
                  corpus=count("corpus_article"), warnings=len(warnings))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
