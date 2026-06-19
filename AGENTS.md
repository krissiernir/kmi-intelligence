# AGENTS.md — guide for AI agents working in this repo

**What this is:** a heavy, source-traceable knowledge base of everything KMÍ
(Kvikmyndamiðstöð Íslands / Icelandic Film Centre) offers and has funded. It exists to be
**queried, turned into prompt packs, and embedded for RAG** from other projects.

If you read nothing else, read this section + `docs/ARCHITECTURE.md` + `docs/STRUCTURE.md`.

## The one rule that matters: two layers
```
data/curated/*.json   = SOURCE OF TRUTH. Hand/AI-edited. Every record has _meta.sources[] + confidence.
        │  (make build)
        ▼
build/                = GENERATED. Never hand-edit. Delete & rebuild anytime.
   kmi.db             relational SQLite (query this)
   prompt_packs/      Markdown + JSON context bundles (paste into prompts)
   embeddings/        chunks + vectors (RAG)

data/raw/             = immutable provenance (downloaded PDFs, HTML snapshots, original manual JSON)
data/staged/          = machine-extracted drafts awaiting promotion to curated/
```
- **Edit only `data/curated/`** (and review `data/staged/`). Then run `make build`.
- **Never hand-edit anything in `build/`** — it's overwritten on every build.
- **Never mutate `data/raw/`** — it's the evidence trail.

## Provenance is mandatory
Every curated record carries:
```json
"_meta": { "sources": ["src.id", ...], "confidence": "verified|needs_verification|inferred|sample", "checked_at": "YYYY-MM-DD" }
```
`compile.py` **fails the build** if a record references a source id not in `sources.json`.
Don't add a fact without a source. Don't upgrade confidence to `verified` unless it's quoted
from an official source (a `data/raw/` artifact). `verified` amounts: see `grant_amounts.json`.

## Commands
```
make build    # data/curated/*.json -> build/kmi.db (validates provenance + referential integrity)
make parse    # data/raw/uthlutanir/*.pdf -> data/staged/allocations.json   (needs `pdftotext`)
make fetch    # download official KMÍ web pages -> data/raw/html/
make kvik     # ingest kvikmyndir.is Icelandic production catalog (cross-reference source)
make packs    # build/kmi.db -> build/prompt_packs/
make embed-setup   # ONE-TIME: py3.12 venv (.venv-rag) + sentence-transformers
make embed         # -> build/embeddings/   (RAG; default backend = local multilingual-e5)
make rag-search SEARCH="heimildamynd þróunarstyrkur"   # semantic search
make all      # parse + build + packs + embed
make run      # launch the Streamlit producer dashboard over build/kmi.db (uses .venv)
make publish  # rebuild + regenerate the COMMITTED export/ (drop-in files for other projects)
make mcp      # run the MCP server (live querying) — config in .mcp.json
```
The core pipeline (parse/build/packs) is **Python-stdlib only** (run `PYTHONPATH=src python3 -m kmi_intelligence.<module>`); needs `pdftotext` (poppler) for parsing. RAG embedding runs in a **separate py3.12 venv** `.venv-rag` (system py3.14 can't build torch). Backends: `local` (default, free/offline, `intfloat/multilingual-e5-base`), `hash` (lexical placeholder, no deps), `openai`/`voyage` (need API keys). Override model with `KMI_EMBED_MODEL`.

## Where things live (see docs/STRUCTURE.md for the full data dictionary)
- `src/kmi_intelligence/compile.py` — curated JSON → `build/kmi.db` (defines the real schema).
- `src/kmi_intelligence/packs.py` — DB → prompt packs.
- `src/kmi_intelligence/rag.py` — chunk + pluggable embed + search.
- `src/kmi_intelligence/ingest/fetch.py` — snapshot KMÍ web pages.
- `src/kmi_intelligence/ingest/parse_uthlutanir.py` — parse the úthlutanir PDFs → staged allocations.
- `src/kmi_intelligence/ingest/kvikmyndir.py` (series) + `ingest/wikipedia_films.py` (films) — external sources → `productions` table, cross-referenced to `allocations`. `xref_status` = matched / likely_unfunded (release ≥2022, no grant) / ledger_gap (pre-2021, our ledger only covers 2021-24). Title-based match (caveats in STRUCTURE.md). `make kvik` + `make wiki-films`. This is the pattern for adding Nordisk Film & TV / other external sources later.
- `data/curated/` — `sources.json`, `grant_families.json`, `grant_streams.json`, `grant_amounts.json`, `documents.json` (per-doc specs + aliases), `criteria.json` (evaluation axes), `rebate.json`, `process.json`.
- `export/` — COMMITTED drop-in files for other projects: `kmi_full.md` (everything), `kmi_full.json`, `kmi_context.md`. See `export/README.md` for integration methods.
- `src/.../mcp_server.py` — MCP server (10 tools: list_grants, get_grant, get_document_spec, funding_stats, top_recipients, get_rebate, productions, lookup_person, lookup_company, search). Runs in `.venv-rag`.
- `data/curated/documents.json` aliases are matched to each stream's document list at compile time (`stream_documents.doc_key`), so a checklist becomes a full spec.
- `docs/` — `ARCHITECTURE.md` (design), `STRUCTURE.md` (data dictionary), `RECONCILIATION.md` (amount provenance + the max-vs-disbursement distinction).

## Critical domain gotcha
For screenwriting/development grants there are **two different "amounts"**:
- **Application maximum** (`grant_streams.max_amount_isk`) — from the live styrkir pages.
- **Disbursement parts** (`grant_amounts`) — how awards are paid in installments, from the úthlutanir PDFs.
They differ (e.g. feature screenwriting max = 1.5M/1.5M/3.0M, but 2023 disbursement parts = 600k/1.0M/1.4M). Don't conflate them. Read `docs/RECONCILIATION.md`.

## The dashboard
`app/streamlit_app.py` is a read-only producer dashboard over `build/kmi.db`:
Overview · Grant browser · Document matrix · Funding explorer · Productions↔funding · People &
companies · Amounts & rebate · Semantic search. Runs in `.venv` (has streamlit+pandas); the
search page shells out to `.venv-rag`. `make run`.

## Legacy (do not extend)
The retired integer-keyed MVP lives in `archive/mvp-legacy/` (code + seed CSVs) — nothing in the
live project imports it; see `archive/mvp-legacy/README.md`. Superseded design docs are in
`docs/archive/`. Don't build new features on either.

## When you change things
- Adding/curating a fact → edit `data/curated/`, ensure `_meta.sources[]` resolve, `make build`.
- New source data → put raw artifact in `data/raw/`, register it in `sources.json`, then curate.
- Changing the schema → it's defined in `compile.py` (TEXT-keyed). Update `packs.py`/`rag.py` if columns change, and `docs/STRUCTURE.md`.
- Always rebuild (`make all`) and confirm the build prints no provenance errors before finishing.
