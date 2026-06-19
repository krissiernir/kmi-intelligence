# KMÍ Intelligence — Architecture (v2: the extensive knowledge base)

This supersedes the MVP described in `PRODUCT_BRIEF.md` / `DATA_MODEL.md` while keeping
their entities. Goal: a **heavy, extensive, source-traceable database of everything KMÍ
offers and has funded**, reusable as a knowledge source from other projects (query, prompt
packs, and RAG).

## The two-layer model

```
                 (hand/AI curation, with provenance)
  data/curated/  ──────────────────────────────────────────►  SOURCE OF TRUTH
   *.json fact files          │
                              │  compile.py  (validate → normalize)
                              ▼
  build/kmi.db   ◄── relational, queryable (SQLite)           DERIVED
  build/prompt_packs/*.md|json  ◄── denormalized LLM context  DERIVED
  build/embeddings/             ◄── vector index for RAG      DERIVED

  data/raw/      downloaded originals (PDFs, HTML snapshots) — immutable provenance
  data/staged/   machine-extracted drafts awaiting human/AI promotion to curated/
```

**Rule:** humans/AI edit only `data/curated/` (and review `data/staged/`).
Everything in `build/` is generated and disposable (`make build` rebuilds it).
Nothing in `build/` is hand-edited; nothing in `data/raw/` is mutated.

### Why two layers
- The **catalog/rulebook** (grants, gáttir, documents, criteria, process, deliverables,
  rebate, legal) is deeply nested, irregular, low-volume, high-value. It belongs in
  readable, diffable JSON with per-record provenance — not flattened into one DB row.
- The **ledger** (úthlutanir — who got how much, per year) is high-volume and tabular.
  It belongs in a relational table for filtering and aggregation.
- Both compile into one `kmi.db` so consumers get a single queryable artifact, plus
  generated prompt packs / embeddings for non-SQL consumers.

## Provenance is first-class (non-negotiable)
Every curated record carries a `_meta` block:
```json
"_meta": {
  "sources": ["src.kmi_styrkir", "src.uthlutanir_2024_pdf"],
  "confidence": "verified | needs_verification | sample | inferred",
  "checked_at": "2026-06-19",
  "notes": "free text",
  "field_sources": { "max_amount_isk": "src.handritsstyrkir_pdf" }   // optional, per-field override
}
```
`data/curated/sources.json` is the registry every `sources[]` id resolves to.
Confidence ladder: `sample` (placeholder) → `inferred` (AI-derived, unverified) →
`needs_verification` (from a real source but not human-checked) → `verified`.
`compile.py` **fails the build** if a record references a missing source id, and warns on
any record with no sources.

## Acquisition pipeline (`src/kmi_intelligence/ingest/`)
1. `fetch.py` — download official pages + PDFs into `data/raw/`, recording URL, fetch time,
   and content SHA-256 into `sources.json`. Idempotent; re-fetch updates hash + `checked_at`.
2. `parse_uthlutanir.py` — `pdftotext -layout` (or pdfplumber) → row records → `data/staged/`.
3. Human/AI review of staged rows → promote into `data/curated/ledger/allocations.*`.
   Extracted data is **never** auto-promoted to `verified`.

### Known sources (live, verified structure)
- Grant catalog: `…/kvikmyndagerd/styrkir` — 6 families, each linking to portal gáttir.
- Application portal: `umsokn.kvikmyndamidstod.is/web/portal/application.html?id=<GÁTTA_ID>`.
- Ledger: `…/uthlutanir/uthlutanir-fyrri-ara` → 4 yearly PDFs (2021–2024) on `kmi.payload.is`.
- Process/deliverables, endurgreiðslukerfi, leiðbeiningar, log-og-reglugerdir pages.

## Compiled DB (extends the 12-table MVP schema)
New tables capture nuance the flat `grants` row lost:
- `grant_families` — the 6 top-level families (handrit, þróun, framleiðsla, eftirvinnsla,
  endurgreiðsla, aðrir) × format track.
- `grant_streams` — the actual application gáttir (e.g. `CUPCLS` = Leikin mynd Handritsstyrkur I):
  gátta_id, portal_url, stage, max_amount_isk, payment_split, newcomer rules.
- `stream_documents` — required/recommended/strategic docs **per stream** (not per family).
- `naming_conventions` — file-naming + format rules per document type.
- `process_stages` — vilyrðisbréf → úthlutunarsamningur → lokaskil, with checklists.
- `deliverables` — final-delivery checklist (KMÍ + Kvikmyndasafn skilaskylda).
- `rebate` — endurgreiðslukerfi (25%/35%, 3 stages, 18-month/300M rule).
- `regulations` — reglugerð 229/2003, kvikmyndalög, etc.
- `allocations` — the ledger (kept from MVP, now populated for real from PDFs).

## Consumers (the three output surfaces)
1. **Programmatic** — open `build/kmi.db` from Python/JS/CLI; or read `data/curated/*.json`.
2. **Prompt packs** — `build/prompt_packs/`: per-stream briefs, full-catalog digest,
   funding-pattern summaries (Markdown + JSON) to drop into other projects' prompts.
3. **RAG** — `build/embeddings/`: chunked + embedded curated facts + ledger summaries.

## Build commands
```
make fetch     # download/refresh raw sources
make parse     # raw PDFs -> data/staged
make build     # curated/ -> build/kmi.db (validate provenance + referential integrity)
make packs     # build/kmi.db -> build/prompt_packs
make embed     # curated/ -> build/embeddings  (RAG)
make all       # build + packs + embed
```
```
