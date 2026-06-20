# STRUCTURE.md — folder layout + database data dictionary

Companion to `AGENTS.md` (rules) and `ARCHITECTURE.md` (design). This is the map.

## Directory tree
```
kmi-intelligence/
├─ AGENTS.md                  read first: rules for agents
├─ README.md                  human overview
├─ Makefile                   parse/fetch/ingest/build/packs/embed/mcp/run targets
├─ requirements.txt           dashboard deps (streamlit/pandas); core pipeline is stdlib-only
├─ .mcp.json                  MCP client config (live querying via mcp_server.py)
│
├─ data/
│  ├─ curated/                ← SOURCE OF TRUTH (edit here)
│  │   ├─ sources.json          source registry; every _meta.sources[] id resolves here
│  │   ├─ grant_families.json   6 top-level grant families
│  │   ├─ grant_streams.json    22 application streams (gáttir) + amounts/docs/rules
│  │   ├─ grant_amounts.json    authoritative disbursement amounts by year (from PDFs)
│  │   ├─ documents.json        per-document specs (purpose, proof, limits, file-naming) + aliases
│  │   ├─ criteria.json         evaluation axes advisors weigh
│  │   ├─ rebate.json           endurgreiðslukerfi (25%/35% + conditions)
│  │   └─ process.json          contract process + final delivery + film-archive deposit
│  ├─ raw/                    ← immutable provenance (never edit)
│  │   ├─ uthlutanir/           yearly allocation PDFs 2021-2024 (+ .txt extractions)  [committed]
│  │   ├─ manual/               the user's original hand-curated JSON/TXT inputs        [committed]
│  │   ├─ wikipedia/            Wikipedia Icelandic FILMS list (wikitext)               [committed]
│  │   ├─ producers/            producers.is SÍK félagaskrá snapshot                    [committed]
│  │   ├─ site/, html/          KMÍ web/sitemap mirror (re-fetchable)        [gitignored: heavy]
│  │   ├─ kvikmyndir/           kvikmyndir.is series list + detail cache     [gitignored: heavy]
│  │   ├─ imdb/                 IMDb bulk-dataset principals (FALLBACK)    [gitignored: license]
│  │   └─ imdb_full/            IMDb full credits via imdbinfo (PRIMARY)   [gitignored: license]
│  └─ staged/                 machine-extracted drafts (allocations.json, productions_*) [gitignored]
│
├─ build/                     ← GENERATED (gitignored; `make` rebuilds)
│  ├─ kmi.db                    the queryable SQLite database (see schema below)
│  ├─ prompt_packs/             kmi_context.md, catalog.*, funding_patterns.*, streams/<GATTA>.md
│  └─ embeddings/               chunks.jsonl + index.jsonl (RAG)
│
├─ export/                    ← COMMITTED drop-in for other projects (make publish)
│  ├─ kmi_full.md / .json       everything in one file (catalog + doc specs + amounts + funding)
│  ├─ kmi_context.md            compact digest
│  └─ README.md                 integration methods (Claude Project / API / MCP / programmatic)
│  (NOTE: export/ is curated KMÍ data only — IMDb-derived fields are NEVER published here)
│
├─ src/kmi_intelligence/
│  ├─ compile.py              curated/*.json (+ data/raw/imdb_full fold) → build/kmi.db (the schema)
│  ├─ packs.py                build/kmi.db → build/prompt_packs/
│  ├─ rag.py                  chunk + pluggable embed + cosine search (.venv-rag)
│  ├─ mcp_server.py           live MCP query server (.venv-rag)
│  └─ ingest/
│      ├─ fetch.py              snapshot KMÍ web pages / mirror sitemap → data/raw/site|html/
│      ├─ parse_uthlutanir.py   úthlutanir PDFs → data/staged/allocations.json
│      ├─ kvikmyndir.py         kvikmyndir.is series → data/staged/productions_series.json
│      ├─ wikipedia_films.py    Wikipedia films → data/staged/productions_films.json
│      ├─ producers_is.py       SÍK félagaskrá → data/staged/companies_producers.json
│      ├─ imdb_datasets.py      IMDb bulk principals (FALLBACK) → data/raw/imdb/
│      ├─ imdb_enrich.py        IMDb full credits via imdbinfo (PRIMARY) → data/raw/imdb_full/
│      └─ imdb_verify.py        validate our tconsts against IMDb title.basics
│
├─ app/streamlit_app.py       producer dashboard (read-only over build/kmi.db; runs in .venv)
├─ docs/                      ARCHITECTURE / STRUCTURE / RECONCILIATION  (+ docs/archive/ superseded)
└─ archive/mvp-legacy/        retired integer-keyed MVP (code + seed CSVs) — not used; see its README
```
Virtualenvs (all gitignored): `.venv` (dashboard: streamlit+pandas), `.venv-rag` (py3.12: RAG +
MCP SDK, `make embed-setup`/`mcp-setup`), `.venv-imdb` (py3.12: imdbinfo, `make imdb-setup`).

## Database schema (`build/kmi.db`)
TEXT-keyed. Built by `compile.py`.

### Catalog (the rulebook)
- **sources**(`id` PK, title, url, source_type, local_path, content_sha256, fetched_at, checked_at, notes)
  — every claim's provenance resolves here.
- **grant_families**(`id` PK, name_is, name_en, purpose, format_tracks_json, subtypes_json, confidence, sources_json)
  — 6 families: handrit, throun, framleidsla, eftirvinnsla, endurgreidsla, annad.
- **grant_streams**(`id` PK, gatta_id, name_is, name_en, family→families, format_track, stage, level,
  portal_url, purpose, **max_amount_isk**, **amount_basis**, payment_split, rules_json, notes,
  confidence, checked_at, sources_json) — the 22 application gáttir. `max_amount_isk` = application
  cap (null = scope-dependent); `amount_basis` explains the figure + its source.
- **stream_documents**(stream_id→streams, requirement_level, document_text, doc_key→documents) —
  required/newcomer/optional documents per stream (138 rows; `doc_key` links to the full spec).
- **documents**(`doc_key` PK, name_is, name_en, purpose, what_it_must_prove, format_limit,
  naming_convention, common_weaknesses, aliases_json, confidence, sources_json) — 24 canonical
  document specs (what each must prove, page/format limits, file-naming convention).
- **criteria**(`id` PK, name_is, name_en, description, evidence_examples, red_flags, confidence,
  sources_json) — the evaluation axes advisors weigh.
- **grant_amounts**(family, format_track, year, stage_note, structure, parts_json, total_isk, quote,
  source→sources, source_line, confidence) — authoritative DISBURSEMENT amounts by year, quoted
  verbatim from the úthlutanir PDFs. Distinct from `max_amount_isk` (see RECONCILIATION.md).
- **rebate**(id PK, name_is, name_en, general_pct, general_basis, enhanced_pct, enhanced_conditions,
  regla_18_manuda, audit_trail, confidence, sources_json) — the production rebate.
- **rebate_stages**(rebate_id, ord, id, name_is, description, stream_id) — vilyrði/hlutaútborgun/útborgun.
- **process_stages**(process_id, ord, id, name_is, condition, deadline_months, regulation_ref, submit_email)
- **process_checklist**(stage_id, title, description) — final-delivery (lokaskil) checklist.
- **process_forms**(stage_id, title, format, url) — official forms/eyðublöð.
- **film_archive_links**(deposit_id, link_key, url) — Kvikmyndasafn skilaskylda links.

### Ledger (what KMÍ funded)
- **allocations**(`id` PK, year, project_title, family, subtype, format_track, applicant, company,
  producer, director, writer, amount_isk, total_isk, commitment_isk, commitments_json, source_id→sources,
  raw_line, confidence) — **793 awards, 2021-2024**, parsed from the úthlutanir PDFs. `amount_isk` =
  current-year grant (styrkur); `commitment_isk`/`commitments_json` = future-year vilyrði; `raw_line`
  preserved for audit.

### Zone 2 — landscape entity graph (the spine; reads Zone 1, never written-to by it)
- **title**(`id` PK, kvik_id, imdb_tconst, title, year, kind [film|series|documentary|short], status,
  region, director, ..., kmi_funded, kmi_total_isk, **xref_status**, matched_json, confidence,
  **IMDb facts**: imdb_rating, imdb_votes, imdb_award_wins, imdb_award_noms, worldwide_gross_usd,
  production_budget, imdb_genres_json, imdb_countries_json, imdb_akas_json, imdb_enriched) —
  **919 titles** = production catalog (380: Wikipedia films `make wiki-films` + kvikmyndir.is series
  `make kvik`) ∪ every distinct úthlutanir project (allocation-derived). `xref_status`: `matched` /
  `likely_unfunded` (release ≥2022, no grant) / `ledger_gap` (pre-2021, ledger only covers 2021-24).
  **175 titles** carry IMDb facts (`imdb_enriched=1`). The IMDb fact columns are IMDb-derived →
  **NEVER ship them in export/** (license). The `productions` VIEW = `SELECT * FROM title` (back-compat).
- **person**(`id` PK, display_name, name_norm, **imdb_nconst** (strong key), region, primary_roles,
  credit_count, source, confidence) — **5,587 people** (5,149 with an IMDb `nconst`; 438 úthlutanir-only).
  ER: nconst dedupes; same name + different nconst stays DISTINCT (never merged). úthlutanir people get
  their nconst *claimed* on exact-name match (251 such links, e.g. Friðrik Þór nm0296144 = 3 ledger + 27 IMDb credits).
- **company**(`id` PK, name, name_norm, type [production|distribution|sales|vfx|misc], is_sik_member,
  website/email/phone/address, kmi_grants_count, kmi_total_isk, kmi_years_json, **imdb_conmst**, ...) —
  **1,019** (40 SÍK + 264 allocation-derived + 715 IMDb production/sales/distribution cos; 728 carry a
  `conmst`). KMÍ funding rollup on the Icelandic ones.
- **title_credit**(title_id→title, person_id→person, **role**, **job**, source, confidence) — **11,940**
  edges. `role` = úthlutanir {director|writer|producer} ∪ full IMDb departments (cast, cinematographer,
  sound_department, camera_department, editor, production_manager [≈line producer], make_up_department,
  visual_effects, art_department, costume_designer, …). **Gaffers/electricians are under
  `role='camera_department'` with `job='Camera and Electrical Department'`** — IMDb's own grouping, kept
  in `job` (558 rows). The **people matrix** = pivot/self-join this (see `lookup_person`).
- **title_company**(title_id, company_id, role, source, confidence) — **1,727** edges (úthlutanir
  producer links ∪ IMDb production/sales/distribution).
- **award**(title_id→title, allocation_id→allocations, year, amount_isk, family, source) — **791**;
  the title-resolved view of the Zone-1 ledger (one authoritative ISK figure lives in `allocations`).
  IMDb award *tallies* live on `title` (wins/noms), NOT here — this table is KMÍ-allocation-specific.
- **alias**(entity_type [company|title], raw_string, raw_norm, entity_id, source, match_method,
  confidence, status) — **907** resolution-log rows. ER policy: strong-key/exact-norm auto-link;
  fuzzy candidates park `status='unresolved'` (33) for human review — **never silently merged**.
  Probabilistic dedup: `resolve.py` (Splink, in `.venv-er`; `make resolve`) scores company duplicates
  on name + **shared films** + type → `data/staged/merge_candidates.json`. You confirm/reject in a
  one-page UI (`app/review.py`, `make review`) → `data/curated/entity_merges.json` (committed source
  of truth), which `compile.py` applies at build (dropped name collapses into the canonical, logged in
  `alias` as `match_method='manual_merge'`). Strong-key links (IMDb conmst) stay deterministic.

Ingesters: `ingest/{kvikmyndir,wikipedia_films,producers_is}.py` + `ingest/imdb.py` (one module,
subcommands `datasets|enrich|verify|resolve`). The IMDb fold (B4) lives in `compile.py`, reading
`data/raw/imdb_full/<tt>.json` (full credits via the `imdbinfo` library, run from `.venv-imdb`;
`src.imdbinfo` PRIMARY, `src.imdb_datasets` fallback). `imdb resolve` finds tconsts for catalog titles
that lack one (writes `data/curated/imdb_links.json`, which `compile.py` backfills). MCP: `lookup_person`,
`lookup_company` (generated dossiers). Films behind kvikmyndir.is Algolia were avoided for CC-licensed Wikipedia.

### Zone 3 — CORPUS + landscape facts (reads Zone 1/2; grant tools NEVER join these)
Source: Klapptré.is (`src.klapptre`) via its WordPress REST API. Journalistic/copyrighted →
**local-only, never committed, never in export/** (raw under `data/raw/klapptre/`, gitignored).
`ingest/klapptre.py` is both the ingester and the extractor; `ingest/textclean.py` cleans article
HTML (drops shortcodes/captions + frequency-detected boilerplate). The Zone 3 build lives in
`compile.py` (lazy-imported, so the core build never depends on it).
- **corpus_article**(`id` PK, source, ext_id, date, year, url, slug, title, categories_json,
  primary_category, tags_json, body_chars) — **1,705** articles (Phase-1 fact categories).
- **corpus_mention**(article_id, entity_type [title|person|company], entity_id, raw_string, method,
  confidence) — article→entity links (headline/table resolution; unresolved kept with NULL entity).
- **lx_admissions**(`id` PK, title_id, film, date, year, **scope** [IS|WW], week_admissions,
  total_admissions, gross_isk, weeks_in_release, article_id, source, confidence) — box office parsed
  from HTML tables. `scope='IS'` domestic vs `'WW'` worldwide (the "á heimsvísu" roundups); admissions
  >500k are dropped as mislabeled ISK gross. **1,148** rows.
- **lx_viewership**(title_id, title_text, channel, viewers, rating_pct, episodes, …) — TV viewership
  (Áhorfstölur), incl. the **channel** (RÚV/Stöð 2). **404** rows.
- **lx_review**(title_id, subject, outlet, date, headline, …) — reviews (Gagnrýni); score is left NULL
  unless explicit (never fabricated). **684** rows.
- **lx_award**(title_id, person_id, subject, result [win|nomination], award_hint, year, headline, …) —
  Verðlaun(win)/Tilnefningar(nomination). **575** rows.
Run `make klapptre` to refresh; `KMI_CATS=all` mirrors the whole site (later RAG phase).

## Common queries
```sql
-- A grant's full requirements
SELECT * FROM grant_streams WHERE gatta_id='CUPCLS';
SELECT requirement_level, document_text FROM stream_documents WHERE stream_id='leikin.handrit_1';

-- Funding by year / family / company
SELECT year, SUM(amount_isk) FROM allocations WHERE amount_isk IS NOT NULL GROUP BY year;
SELECT company, SUM(amount_isk) t FROM allocations GROUP BY company ORDER BY t DESC LIMIT 10;

-- Disbursement vs application max
SELECT gatta_id, max_amount_isk, amount_basis FROM grant_streams WHERE family='handrit';
SELECT family, format_track, year, parts_json FROM grant_amounts ORDER BY family, year;
```

## Confidence ladder
`sample` < `inferred` (AI-derived) < `needs_verification` (real source, unchecked) < `verified` (quoted from an official artifact in data/raw/).
