# NEXT_STEPS.md — open work & current state

Snapshot for resuming after a context reset. Companion to `STRUCTURE.md` (the map) and
`ARCHITECTURE.md` (the design). Updated 2026-06-20.

## Mission (expanded)
Not just a "KMÍ copilot" — an **Icelandic film-industry knowledge graph** for learning and
navigating the industry. KMÍ is ONE well-traced source (allocation ledger **2021–24 only**), not
the source of truth. **Hard semantic rule:** absence of data is never asserted as fact — no title
is "unfunded" and no film has "no director"; we model `known | unknown`, never a negative-from-absence.

## Done 2026-06-20 (phase 2 groundwork — "semantics + persons first")
- **Funding honesty:** `xref_status` is now tri-state `matched / no_record_in_window / before_window`
  (255 pre-2021 titles no longer falsely "probably unfunded"; threshold fixed 2022→2021). App reworded.
- **Director honesty:** backfilled `title.director` from credits (321 titles); rest render "óþekkt", never "no director".
- **Careers:** `make imdb-careers` (808 filmographies pulled) → folded `career_first_feature_year` +
  `career_json` for **711 people**; `credit_count` relabelled catalog-scoped; person page shows real career first-feature.
- ruflo MCP decision: **read-only research only** (writes stay on the provenance pipeline).

## Current state (live `build/kmi.db`)
- **Zone 1 — grants:** 6 families · 22 streams · 24 doc-specs · 20 amount-records · rebate/process · **793 allocations** (2021–24). Complete.
- **Zone 2 — spine:** **919 titles · 7,212 people · 1,389 companies · 15,981 credits · 2,414 title↔company · 791 awards · 944 aliases.** IMDb: 287 enriched, 289/380 catalog have a tconst. Deduped (139 confirmed merges).
- **Zone 3 — corpus + facts:** **corpus_article 5,652** (5,311 Klapptré 2013→2026 + 341 KMÍ) · lx_admissions 1,148 · lx_viewership 543 · lx_review 684 · lx_award 575 · corpus_mention 1,721.
- **Reference:** 294-term lexicon. **32 sources** registered. DB ~20 MB.
- **RAG:** 18,934 chunks → dense e5 (324 MB) **+ BM25-over-Miðeind-lemma** → hybrid (RRF), IS+EN, local.
- **App (Bíómonsi, `make run`):** Icelandic, plotly cockpit, clickable Framleiðslur profiles, 🚩 flagging (`make flags`), 💬 Ask Bíómonsi (Anthropic text-to-SQL, key in gitignored `.env`).
- **Tooling:** `make health` · `make validate` (Pandera) · `make resolve`/`review` (Splink dedup) · `make lint` (ruff) · activity log. Venvs: `.venv` (dash), `.venv-rag` (RAG+NLP), `.venv-imdb`, `.venv-er` (Splink), `.venv-nlp` (Miðeind).

## Open work (priority order)

### 🔴 Phase 2 — industry graph + persons (active focus)
A. ✅ **DONE — Older KMÍ úthlutanir backfill (pre-2021).** `ingest/uthlutanir_archive.py` recovers the
   2015–2020 allocation tables from the Internet Archive (the new CMS dropped them) → **779 pre-2021
   allocations**, ledger now 2015–24. `make parse-archive` (harvest+parse) → `allocations_archive.json`,
   folded by compile alongside the PDFs. Result: matched 603→940, before_window 255→223. Source-traced
   (`...wayback`, needs_verification). *Refinements left:* pre-2015 ("fyrri-ár" page), vilyrði→grant
   reconciliation, ER of the new pre-2021 titles/people against the existing spine.
B. **Deep persons enrichment** — *started:* `app/person_profile.py` is a meeting-ready dossier
   (projects, credits, real first-feature, **KMÍ funding approvals matched to writer/director/producer
   over 2015–24** w/ by-family breakdown, top collaborators, copy-paste markdown export). *Still to do:*
   web/IMDb narrative bio (training, breakthrough), per-collaborator drill-down ("X projects with Y"),
   and folding NGO board/membership context once C lands. Local-only provenance.
C. **NGO / organizations zone + connection map** — scrape the 13 `db-import-staging/manualresources.md`
   sites (guilds, unions, academies, festivals, agencies) to their fullest with **scrapling** (raw saved
   as provenance); model `organization` + `membership`/`role`/`board` → people↔orgs↔films graph.
   **ruflo = read-only research fan-out only**; writes go through a structured ingester + Splink/Miðeind.

### 🟢 Prepped & quick (staging did the prep — `db-import-staging/`)
1. **financing_landscape zone** — fold the 30 financing/macro facts (`literature/literature_facts.json`, skip the 1 `dated`) into a new isolated table + register the 6 lit sources (`literature/sources.proposed.json`). Same pattern as the lexicon import.
2. **confirms_db bump** — add the academic corroboration to the 92%-day-1 record (+ rebate conditions); raise confidence, don't duplicate.
3. **Macro refresh** — 2023–24 figures (turnover 36bn, ~1,090 companies, 86% wouldn't-have-come) as `updates_db`.

### 🟡 Build (medium effort, high value)
4. **Corpus mention→entity linkage** — wire the validated **Miðeind +90**: a `corpus_resolve` step (runs in `.venv-nlp`) that re-resolves headline mentions via `textclean.normalize_name`/`entities` → folds better `title_id`/`person_id` onto `corpus_mention`/`lx_*`. Currently string-matched only (~55→62% on reviews/awards in testing).
5. **More ER review** — ~7 skipped company candidates + pseudonym **manual merges** (e.g. *Ólaf de Fleur* ⇄ *Ólaf Jóhannsson* — not auto-detectable; `entity_merges.json` person.merges supports manual entries).

### 🔵 Ingestion gaps (real, not blocking)
6. **producers.is full crawl** — only the félagaskrá (40 SÍK members) is in; the rest is uncrawled, and that URL **404'd on re-check** (needs the current path).
7. **Legal/regulatory text** — Kvikmyndalög 137/2001 + Reglugerð 229/2003 registered as sources, not structured.
8. **~91 catalog titles without a tconst** (2026 upcoming + not-on-IMDb) + the **41 parked tconst candidates** (`data/staged/imdb_resolve_review.json`) awaiting human review. KMÍ never published a 2024 áhorf page (their omission).

### 🟣 App / deploy
9. **Deploy** — DEPLOYMENT_PLAN.md: Mac mini behind Tailscale for the trusted few. The flagging write (`logs/review_queue.jsonl`) is the app's only write; nightly atomic-swap rebuild is unaffected.
10. Optional polish: wire the collaborator **network** (`viz.network`) into the People page; full Icelandic relabel (page routing keys are still English internally — cosmetic).

### ⚪ Parked / revisit-when-triggered
- **DuckDB + Parquet / Polars** — the corpus is now heavy (5.6k articles); trigger met if analytics get slow.
- **sqlite-vec** — in-DB vectors (we built a custom index instead).
- **the-numbers.com** — reference only, no scraper (proprietary, weak IS coverage). By design.

## Recommended next session
**Phase 2 is the active focus.** Next concrete step: **A (older KMÍ úthlutanir backfill)** — fetch the
pre-2021 annual allocation PDFs and parse them, directly shrinking `before_window`. Then **B (deep
persons enrichment)** and **C (NGO scrape + connection map)**. The 🟢/🟡 items below stay queued.

## Hard rules (don't regress)
- IMDb data + the Klapptré corpus are **local-only, never committed, never in `export/`** (license/copyright).
- Zone 1 grant core never depends on Zone 2/3; the build is stdlib-only (heavy tools live in venvs).
- Entity resolution: strong-key auto-link; fuzzy → human review, **never silently merged**.
