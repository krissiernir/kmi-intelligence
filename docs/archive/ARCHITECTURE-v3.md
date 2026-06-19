# ARCHITECTURE v3 — the Icelandic film/TV landscape knowledge graph

**Status:** design proposal (no code yet). Supersedes the framing in `ARCHITECTURE.md` (which
stays valid for the KMÍ core). Builds on what exists today; nothing here breaks the current
grant catalog, document matrix, or funding ledger.

## 1. The problem this solves
We are going from "a KMÍ grant tool" to "a knowledge base of an industry," fed by many sources
(KMÍ site, kvikmyndir.is, Wikipedia, statistics pages, news, later Nordisk/IMDb/…). Two hard
requirements, in tension:

1. **The basic functions must never break.** Grant calling, the document matrix, funding stats —
   these must stay exact and stable no matter how many messy sources we add.
2. **Almost everything is potentially useful** — even news articles — *as context*. We want it
   retrievable, mined, and connected, without it leaking into (1).

The resolution is **zoning with a one-way dependency rule**: model the domain as a graph, split
it into trust/stability zones, and forbid the stable core from ever depending on the volatile
layers. Then "break" is structurally impossible in the wrong direction.

## 2. Principle: model the domain, not the sources
Organize around the **entities of the domain** (title, person, company, …), not around where data
came from. Sources *feed* entities. A grant query touches grant tables; it cannot touch news
because news is not part of the grant sub-graph — not by convention, but by schema.

## 3. The three zones (the heart of the design)

```
        ┌─────────────────────────────────────────────────────────────┐
ZONE 3  │ CONTEXT / CORPUS   news, policy text, transcripts            │
        │   corpus_article, corpus_mention                             │
        │   trust: unstructured · powers: RAG / knowledge / mining     │
        └───────────────┬─────────────────────────────────────────────┘
                        │ may reference entity ids (mentions only) ▲ nothing depends on Zone 3
        ┌───────────────┴─────────────────────────────────────────────┐
ZONE 2  │ EXTENDED / LANDSCAPE GRAPH                                    │
        │   entities: title, person, company, body                     │
        │   links:    title_credit, title_company, award(title↔program)│
        │   facts:    title_admissions, title_viewership, stat_*        │
        │   trust: mixed, source-tagged · powers: analytics, slates    │
        └───────────────┬─────────────────────────────────────────────┘
                        │ may READ Zone 1 (program_id, allocation)  ▲ Zone 1 never depends on Zone 2
        ┌───────────────┴─────────────────────────────────────────────┐
ZONE 1  │ CORE — canonical KMÍ truth (the stable contract)             │
        │   grant_families, grant_streams, stream_documents,           │
        │   documents, criteria, grant_amounts, rebate*, process*,     │
        │   allocations                                                │
        │   trust: verified / needs_verification (KMÍ only)            │
        │   powers: grant calling · document matrix · funding stats    │
        └─────────────────────────────────────────────────────────────┘

ZONE 0  cross-cutting: `source` registry · data/raw/* snapshots
```

**The dependency rule (a DAG, one direction only):**
- Zone 1 depends on **nothing**. It can be built, queried, exported, and shipped entirely on its own.
- Zone 2 **may read** Zone 1 (e.g. link an `award` to a `grant_program`); Zone 1 has **no foreign
  key, view, or query path into Zone 2**.
- Zone 3 may *reference* Zone 1/2 entity ids (via `corpus_mention`) but **nothing depends on Zone 3.**

**Consequences (exactly your requirement):**
- Delete or corrupt all of Zone 3 → Zones 1 & 2 are unaffected.
- Delete or corrupt Zone 2 → grant calling, the matrix, and funding stats (Zone 1) are unaffected.
- A "grant" query/tool reads Zone 1 only and **cannot** return a news article.

## 4. How the zones are enforced (not just promised)
1. **Schema FKs point inward only.** Core tables reference core tables. Extended may reference core.
   Corpus references entity ids softly (no enforced FK, since articles predate/outlive entities).
2. **Build order + separability.** `compile.py` builds Zone 1 first and can emit a **core-only DB**
   with no Zone 2/3 present. Zone 2 and Zone 3 are separate build steps that *add* tables.
   Suggested: keep one `build/kmi.db` but allow `build/kmi_core.db` (Zone 1 only) for consumers
   that want the guarantee in physical form.
3. **Naming makes the zone obvious.** Zone 1 = current names (unprefixed). Zone 2 = entity names
   (`title`, `company`, `person`) + `lx_*` for landscape facts (`lx_admissions`, `lx_viewership`,
   `lx_stat_budget`). Zone 3 = `corpus_*`. No table's zone is ambiguous.
4. **Consumption surfaces are zone-scoped.** Each MCP tool / dashboard page / prompt pack declares
   which zone(s) it reads. The grant tools and the document matrix are Zone-1-only by definition.
   A separate `search`/`context` tool reads Zone 3. They never share a query.

## 5. Trust model (why news can't pollute facts)
Confidence ladder, unchanged: `sample < inferred < needs_verification < verified`. Add a zone rule:
- **Zone 1 admits only KMÍ-authoritative data.** Nothing derived from news or third parties is
  ever written into a Zone 1 table.
- **A news article is a *source of facts*, not a fact.** If an article says "Film X drew 50,000
  admissions," that becomes an `lx_admissions` row (Zone 2) with `source` = the article and
  `confidence = needs_verification`. The *fact* lands in the right typed table; the *article text*
  stays in `corpus_article` (Zone 3). You get the signal; the corpus never leaks into a fact query.

So there are two registers: a **structured layer** (facts you quote/query, Zones 1–2) and a
**context layer** (text you search/mine, Zone 3), bridged only by explicit, typed promotion.

## 6. Entity model (the Zone 2 spine)
- `title` — any work (film/series/doc/short); canonical id + kvik_id, imdb_id, year, kind, status.
  *(today's `productions` grows into this)*
- `person`, `company` (type: production/service/post/distributor/broadcaster), `body` (KMÍ, RÚV, funds, festivals)
- Links: `title_credit` (title↔person, role), `title_company` (title↔company, role),
  `award` (title↔grant_program, year, amount — the title-resolved view of Zone 1 `allocations`)
- Facts: `lx_admissions`, `lx_viewership`, `lx_festival`, `lx_imdb` (later);
  sector timeseries: `lx_stat_budget`, `lx_stat_gender`, `lx_stat_sector`

## 7. Source-onboarding contract (so "every link" scales)
Adding a source never changes the schema — only adds rows. Each source:
1. gets a row in `source` (id, name, type ∈ {grant_registry, production_catalog, stats, news, law,
   external_fund}, url, license, reliability, refresh_cadence, last_fetched);
2. gets one ingester `ingest/<source>.py` → `data/raw/<source>/` → `data/staged/<source>_*.json`;
3. maps its records onto **existing** entities/facts (or, rarely, a new fact table if it's a
   genuinely new *kind* of fact).
The schema changes only when a new *kind of fact* appears, never when a new *source* appears.

## 8. Entity resolution (the hard part = the real value)
"Snerting" the funded project, the box-office row, and the news headline — and "RVK Studios"
across all of them — must resolve to one `title` / one `company`. Approach:
- canonical entity tables + an `alias` table (source string → canonical id, with match method +
  confidence); start with normalized title+year (we already do this productions↔allocations) and
  kvik_id/imdb_id as strong keys; keep unresolved rows visible, never silently merged.
- This unlocks the payoff queries: *a company's full slate — funded vs self-financed, and how each
  performed (admissions/viewership)*; *do KMÍ-funded films out-draw unfunded ones?*

## 9. Consumption surfaces, by zone
| Surface | Reads | Note |
|---|---|---|
| Grant tools, document matrix, prompt packs (catalog) | Zone 1 | the stable contract — never sees Zones 2/3 |
| Funding analytics, "slates", funding-vs-outcome | Zone 1 + 2 | joins through entities |
| Semantic search / "knowledge" / mining | Zone 3 (+ 1/2 facts as chunks) | the news goldmine, isolated |

## 10. Migration from today (incremental, non-breaking)
1. Keep Zone 1 exactly as is (it already works). Add the `source` registry formally.
2. Promote `productions` → `title`; turn the fuzzy productions↔allocations match into a real
   `award` link + `alias` table.
3. Add Zone 2 facts: `lx_admissions`, `lx_viewership`, `lx_stat_*` (the landscape pages).
4. Add `company`/`person` entities + credits (enables slate queries).
5. Add Zone 3: `corpus_article` + `corpus_mention` (news), feeding RAG; promote extractable facts
   into Zone 2 with provenance.

## 11. Recommended build sequence
Phase A — lock Zone 1 as a frozen contract + add `source` registry + emit `kmi_core.db`.
Phase B — entity spine (`title`, `award`, `alias`) by refactoring productions/allocations.
Phase C — landscape facts (admissions, viewership, budget, gender) — highest analytic payoff.
Phase D — companies/people + credits (slates).
Phase E — corpus (news) + mentions + RAG over the lot.

## 12. Open questions for review
- Physical split? one `kmi.db` with zoned tables (simpler) vs separate `kmi_core.db` / `graph.db` /
  `corpus.db` (hardest guarantee). Recommendation: one DB, zoned + a core-only export.
- Entity-resolution strictness: auto-merge threshold vs. always-human-review for medium-confidence.
- News scope: all ~273 articles + ongoing refresh, or a curated subset?
- Which external sources first (your landscape finds, Nordisk, IMDb)?
