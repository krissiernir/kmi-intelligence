# ARCHITECTURE — the Icelandic film/TV landscape knowledge graph (consolidated, v3.1)

**Status:** the single design of record (implemented). Earlier drafts are in `docs/archive/`
(`ARCHITECTURE-v3.md`, and the v2 two-layer model `ARCHITECTURE-v2.md`) — this consolidates and
supersedes them. Nothing here breaks the grant catalog, document matrix, or funding ledger.

It folds in four decisions:
1. a **register model** (fact / inference / interpretation) controlling what an LLM sees by default;
2. the **corpus** repositioned as a *leading-indicator* layer, not an afterthought;
3. **concentric geographic scopes** (Iceland → Nordic → Europe) inside one graph;
4. an **entity spine** (person / company / title) with generated dossiers and a people matrix.

---

## 0. What this is for (read this first)
A neutral, source-traceable knowledge base of the Icelandic film/TV landscape (expanding to the
Nordics and Europe), used primarily by **talking to it through an LLM** — "look up this person,"
"who worked on what," "what's happening with X," "do trends here track Scandinavia." The data
stays *un-opinionated ground truth*; reasoning happens at prompt time, not baked in. Two hard rules
carried from v3:

- **The grant functions never break.** Catalog, document matrix, funding stats stay exact and
  stable no matter how many messy sources we add.
- **Almost everything is potentially useful as context** — even news — but must not leak into the
  trusted core.

---

## 1. The model in one picture: three orthogonal axes + a spine

Every table/record sits at a point on three independent axes. Keeping them separate is what makes
the design absorb new sources without new concepts.

```
AXIS A — LAYER (lifecycle):     raw → staged → curated → build
         "how processed / is it source-of-truth or generated"   (from v2)

AXIS B — ZONE (trust/stability, one-way dependency):
         Z1 CORE ◄── Z2 GRAPH ◄── Z3 CORPUS
         "what may depend on what"                              (from v3)

AXIS C — REGISTER (epistemic status → default LLM context):
         fact → inference → interpretation
         "is it true, guessed, or an opinion"                   (new)

DIMENSIONS on the data itself:
   • region/scope: IS → Nordic → Europe   (a filter, not a wall)
   • provenance + confidence on every record   (non-negotiable, from v2)

THE SPINE that ties it together:
   canonical entity (title/person/company/body) + alias + strong keys
   + provenance-tagged edges
```

A new source never adds a concept. It resolves its records to **canonical entities**, attaches
**provenance-tagged edges**, and the rollups (dossiers, matrix, packs) regenerate. The schema
grows only when a genuinely new *kind of fact* appears — never per source (v3 §7 contract).

---

## 2. Axis B — the three zones (the stability guarantee)

```
ZONE 3  CONTEXT / CORPUS    news, policy text, transcripts, press
        corpus_article · corpus_mention
        trust: unstructured · powers: search / leading indicators / mining
                  │ may reference entity ids (mentions only)   ▲ nothing depends on Z3
ZONE 2  EXTENDED / LANDSCAPE GRAPH
        entities: title · person · company · body
        edges:    title_credit · title_company · award · alias
        facts:    lx_admissions · lx_viewership · lx_festival · lx_stat_*
        trust: mixed, source-tagged · powers: matrix · dossiers · slates · trends
                  │ may READ Zone 1 (program_id, allocation)   ▲ Z1 never depends on Z2
ZONE 1  CORE — canonical funding truth (the stable contract)
        grant_families · grant_streams · stream_documents · documents · criteria ·
        grant_amounts · rebate* · process* · allocations
        trust: verified / needs_verification · powers: grant calling · matrix · funding stats
ZONE 0  cross-cutting: source registry · data/raw/* snapshots
```

**Dependency rule (DAG, one direction):** Z1 depends on nothing; Z2 may read Z1; Z3 may *reference*
Z1/Z2 entity ids but nothing depends on Z3. Consequence: corrupt all of Z3 → Z1/Z2 unaffected;
corrupt Z2 → grant calling unaffected; a grant query reads Z1 only and *cannot* return a news article.

**Enforced by, and only by (kept deliberately light):**
- FKs point inward only (core→core, extended→core; corpus references entity ids *softly*, no FK).
- Naming makes the zone obvious: Z1 = current unprefixed names; Z2 = entity names + `lx_*` facts;
  Z3 = `corpus_*`.
- Consumption surfaces are zone-scoped: grant tools/matrix are Z1-only by definition; a separate
  search/context tool reads Z3. They never share a query.

> **Deliberately NOT built now (YAGNI — see §11):** physical DB splits, a separate `kmi_core.db`
> export, separate per-region database files. The zones are a *naming + FK + tool-scoping*
> convention in one `build/kmi.db`. We add a physical split only when a real consumer demands it.

---

## 3. Axis C — the register model (why your data won't pigeonhole an LLM)

Three registers, each with a different **default-context** behavior. This is the mechanism for
"keep logical guesses around, but don't let them cloud things unless I ask."

| Register | Example | Stored as | In default LLM context? |
|---|---|---|---|
| **Fact** | "Snerting drew 44,881 admissions" | typed row, `confidence ≥ needs_verification` | **Yes** |
| **Inference** | "this row probably = that company" | typed row, `confidence = inferred` | **No** — opt-in by confidence filter |
| **Interpretation** | "crime is under-served" | *not in the KB*; a separate opt-in tool only | **No** — never default |

- The **confidence ladder** (`sample < inferred < needs_verification < verified`) is the dial for
  facts-vs-guesses. Default prompt packs / tools filter to `≥ needs_verification`. An "interpreted
  view" tool includes `inferred`.
- **Interpretation/opinion is never authored into the KB.** If wanted later, it is its own
  zone-scoped tool you call deliberately, so it can never anchor a default query.
- This keeps the KB as neutral ground truth — its competitive value is precisely that it doesn't
  hand a consuming model your conclusions.

---

## 4. The entity spine (powers the matrix, the lookup, the dossiers)

Canonical entities are the atoms you maintain. **Parsers emit edges to them; they never author
prose.** A "file on a studio/person" is a *generated projection*, never a hand-file (so it can't
drift from the facts and every line keeps provenance).

```
title    (id PK, kvik_id, imdb_tconst, title, original_title, year, kind, status, region, …)
            ← today's `productions` grows into this
person   (id PK, display_name, imdb_nconst, kvik_person_id, region, primary_roles, …)
company  (id PK, name, imdb_company_id, kvik_company_id, type, region)
            type ∈ production | service | post | distributor | broadcaster
body     (id PK, name, kind)   ← KMÍ, RÚV, funds, festivals, foreign funders

alias    (entity_type, raw_string, entity_id, source, match_method, confidence)
            ← the resolution log; unresolved rows stay VISIBLE, never silently merged

title_credit  (title_id, person_id, role/category, billing_order, source, confidence)
title_company (title_id, company_id, role, source, confidence)
award         (title_id, grant_stream_id, year, amount, source)   ← title-resolved view of Z1 allocations
```

**Strong keys are the spine of the spine.** `imdb_tconst` / `imdb_nconst` / `kvik_id` are
authoritative; fall back to normalized title+year only when a strong key is absent. They are also
the bridge for IMDb enrichment and for cross-region resolution (§6). Resolution is the one
genuinely hard part of this whole project, and it recurs everywhere — invest here, keep a
human-review queue for medium-confidence matches, never auto-merge above an unauditable threshold.

### 4a. The people matrix — falls out of `title_credit`
- **People × films:** pivot `title_credit` (person rows × title columns).
- **Person × person (collaboration network):** self-join `title_credit` on `title_id` → who works
  with whom, how often. In a market this small this is a real edge (who attracts funding, which
  crew precedes a hit).
- **"Who worked on what *when*":** `title_credit ⨝ title(year)` ordered by year = any person's
  career timeline or any company's slate over time.

### 4b. "Look up this person for me" — a generated dossier + one MCP tool
`make profiles` rolls the graph up into one file per entity (`build/profiles/{person,company}/<id>.md|json`):
identity + strong keys · full filmography/slate (funded vs self-financed) · funding attached ·
how their films performed (admissions/viewership) · frequent collaborators · recent news mentions.
Exposed as MCP `lookup_person` / `lookup_company` (joins the existing 8-tool server). That *is* your
meeting-prep "look up this person."

---

## 5. The corpus (Axis B Zone 3) — your leading-indicator layer

Plain definition: a **corpus** is stored text kept as searchable source material (~**6,000**
industry news posts — Klapptré, producers.is, KMÍ frettir — plus press releases, policy, transcripts).

```
corpus_article  (id PK, title, body, url, outlet, published_at, source)
corpus_mention  (article_id, entity_type, entity_id, span?, confidence)   ← the index, and the goldmine
```

- `corpus_mention` is the value, not the search box: it turns loose text into "everything written
  about RVK Studios / this title / this director," and "who's named most this year."
- **Two registers, bridged by typed promotion:** the article *text* lives in Z3 (searchable); any
  hard figure extracted from it ("drew 50,000 admissions") becomes a Z2 `lx_*` row with the article
  as `source` and `confidence = needs_verification`. You get the signal; prose never pollutes a
  fact query.
- **Why it matters here:** admissions/viewership are *lagging* indicators (what already happened).
  News is the *leading* indicator (what's in development, who moved companies, what's being
  financed, festival buzz). In a market this small the news volume actually covers the field.
- **Scale (corrected 2026-06-19):** the corpus is ~**6,000** posts, not 273. Klapptré alone is
  **5,311** (verified via its WordPress REST API `/wp-json/wp/v2/posts` — clean structured fields +
  categories/tags), plus producers.is news and the ~273 KMÍ frettir. At this size "fits in context /
  keyword is enough" no longer holds: **vector embeddings are warranted from the start**, and the
  infra already exists (`.venv-rag`, multilingual-e5-base). Build the `mention` index *and* embed.
- **Mention extraction is an automated entity-linking job, not hand-curation.** At ~6k posts,
  `corpus_mention` is populated by NER + matching against the entity registry's names/aliases, with
  the same human-review queue for ambiguous mentions. The index value and two-register discipline
  above are unchanged — only the volume and the need for automation are.

---

## 6. Geographic scope — concentric rings in ONE graph

Iceland is central; Nordic and Europe are expanding rings, **not separate databases**. Separate
files would recreate entity resolution at every border (the same co-pro under three id spaces).

- **Author separately, serve together:** each source/region gets its own ingester, `data/raw/<source>/`,
  refresh cadence, license, trust — so a broken Lumiere parse can't touch Iceland's curated truth.
  They compile into one graph where **`region` is a filter, not a wall**. "Iceland core" =
  `WHERE region='IS'`, still exportable alone if ever needed.
- **Territory belongs on the *fact*, not the entity:** an admission is a property of *a film in a
  territory*. `lx_admissions(title_id, territory, year, admissions, source)` answers "Iceland vs
  Scandinavia trends" natively — they're just different `territory` values.
- **Conformed dimensions are what make correlation mean anything:** one genre vocabulary, one year,
  one territory list, one entity registry, shared across all regions. Without this, "drama" in KMÍ
  ≠ "fiction" in Lumiere and no topology saves you. *This* is the real work behind "do Iceland and
  Scandinavia correlate," not the file boundary.
- **Catalog generalizes to multi-funder:** add `funder`/`body` + `region` to `grant_families` /
  `grant_streams` so KMÍ is one funder among several (Nordisk Film & TV Fond, Eurimages, Creative
  Europe MEDIA). "List Nordic grants I could apply to" = a region/funder filter on the catalog. The
  never-breaks guarantee holds because each funder's curated source files stay separate even though
  they compile into one table.

Candidate sources (higher-trust than news scraping): **EAO Lumiere** (per-country EU admissions,
incl. Iceland), **Hagstofa Íslands** (official cultural stats), **Gallup Ísland** (actual TV
ratings), **Nordisk Film & TV Fond**, later **IMDb** (§7).

---

## 7. IMDb enrichment (later) — slots in as a source, not a rebuild

Because the `person`/`company` spine exists from the start, IMDb *enriches existing entities*
(adds `nm`/`tt` ids and full credits) rather than introducing people for the first time.
- Source: IMDb bulk **datasets** (title.basics, title.principals, name.basics, title.crew,
  title.akas). **title.akas** carries region-specific title variants → an entity-resolution aid for
  matching Icelandic titles to `tt`.
- Once a title has its `tt` and a person their `nm`, "who worked on what when" resolves cleanly via
  title.principals.
- **License:** IMDb datasets are personal/non-commercial — fine for private intelligence, **not
  redistributable.** Record this in the `source` registry `license` field.

---

## 8. Provenance & confidence (unchanged, non-negotiable)
Every curated record carries `_meta { sources[], confidence, checked_at, notes, field_sources? }`;
`sources.json` is the registry; `compile.py` fails the build on a missing source id. Ladder:
`sample < inferred < needs_verification < verified`. See `ARCHITECTURE.md` §"Provenance is first-class".

---

## 9. Consumption surfaces, by zone
| Surface | Reads | Default register |
|---|---|---|
| Grant tools, document matrix, catalog packs | Zone 1 | facts only |
| Funding analytics, slates, funding-vs-outcome, **people matrix**, **trends** | Zone 1 + 2 | facts; `inferred` opt-in |
| **`lookup_person` / `lookup_company`** (dossiers) | Zone 1 + 2 (+ Z3 mentions) | facts; mentions labeled |
| Semantic search / news / mining | Zone 3 (+ 1/2 facts as chunks) | text + promoted facts |

---

## 10. Build sequence (value-ordered; each step ships something usable)
- **B1 — Entity spine.** Refactor `productions`→`title`; add `person`, `company`, `alias`,
  `title_credit`, `title_company`, `award`. Resolve from sources you already parse (allocations,
  Wikipedia, kvikmyndir). **Ships: the people matrix + a basic `lookup_person`.**
- **B2 — Landscape facts.** `lx_admissions` (with `territory`), `lx_viewership`, `lx_stat_*` from
  the KMÍ áhorf/aðsókn pages. **Ships: trends + rich dossiers.**
- **B3 — Corpus.** `corpus_article` + `corpus_mention` + embeddings over ~**6,000** posts (Klapptré
  5,311 via WP REST API + producers.is + KMÍ ~273); automated entity-linking for mentions; promote
  extractable figures to Z2. **Ships: news in dossiers + semantic search + leading indicators.**
- **B4 — IMDb enrichment.** Add `tconst`/`nconst` + full credits/timeline.
- **B5 — Regions.** Add `region`/`territory` everywhere, multi-funder catalog, Lumiere/Nordisk;
  cross-region correlation.

---

## 11. Deliberately deferred (so we build value, not machinery)
- physical zone DBs / separate `kmi_core.db` export — until a consumer needs the physical guarantee.
- separate per-region database files — `region` is a column; export per-region only on a real need.
- ~~a vector RAG pipeline~~ — **no longer deferred (corpus is ~6,000, not 273):** semantic
  embeddings are warranted from the start; infra already exists (`.venv-rag`). The `mention` index is
  built alongside, not instead.
- an interpretation/recommendation layer — opt-in tool later, never default context.
- elaborate auto-merge ER — start with strong keys + normalization + a visible unresolved queue.

---

## 12. Open questions
- ~~Entity-resolution review: auto-merge vs human-review?~~ **DECIDED (2026-06-19): human-review
  queue.** Auto-accept only strong-key (`imdb_*`/`kvik_id`) or exact title+year matches; every
  fuzzy/medium-confidence candidate parks in a visible `alias` queue (`confidence=inferred`,
  unresolved) for approval. Never silently merged.
- ~~Genre taxonomy?~~ **DECIDED (2026-06-19): IMDb genre vocabulary is canonical.** All sources map
  onto IMDb's genre list; add a thin custom mapping only if an Icelandic category can't be expressed.
- ~~News scope/cadence?~~ **DECIDED (2026-06-19): ingest ALL (~6,000); refresh MANUAL only.**
  Sources: Klapptré 5,311 (clean via WordPress REST API `/wp-json/wp/v2/posts`, structured fields +
  categories/tags), producers.is news (ingestion path TBD), KMÍ ~273. The WP API makes incremental
  refresh trivial (posts after last-fetched) if manual ever becomes a chore. Content-hash diffs flag changes.
- ~~Region-2 source first?~~ **TENTATIVE (2026-06-19): Lumiere first** (structured per-country
  admissions → drops straight into `lx_admissions`). Caveat: no known public API, so ingestion =
  its export/query interface; **confirm the access path at B5** before committing. Nordisk is the
  fallback (closer to the existing KMÍ catalog+ledger patterns).
