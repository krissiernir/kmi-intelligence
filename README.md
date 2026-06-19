# kmi-intelligence

Local-first, source-traceable knowledge base of **everything KMÍ (Kvikmyndamiðstöð Íslands)
offers and has funded**, plus a graph of the surrounding **Icelandic film/TV landscape** — built
to query (SQLite), to generate prompt packs and RAG context for other projects, and to serve live
answers over MCP. Design of record: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); folder + data
dictionary: [docs/STRUCTURE.md](docs/STRUCTURE.md).

## How it's built — two layers

- **`data/curated/*.json`** — the source of truth. Every record carries `_meta.sources[]` and a
  confidence level. The only layer you hand-edit.
- **`build/`** — generated artifacts (`kmi.db`, `prompt_packs/`, `embeddings/`). Rebuilt by
  `compile.py`, never hand-edited.

`data/raw/` holds immutable provenance (PDFs, web snapshots, IMDb pulls); `data/staged/` holds
machine-extracted drafts the ingesters produce before the build folds them in.

## What's in it

**Zone 1 — grant core (the rulebook + ledger):**
- 6 grant families, **22 application streams (gáttir)** with portal links, amounts, payment
  splits, and **138 document requirements**; the rebate scheme; the contract/delivery process.
- **Funding ledger: 793 awards (2021–2024)** parsed from the official úthlutanir PDFs — queryable
  by year / family / company / project.

**Zone 2 — landscape entity graph (the spine):**
- **919 titles** (Wikipedia films + kvikmyndir.is series ∪ every funded project),
  **5,587 people**, **1,019 companies** (incl. 40 SÍK members), **11,940 credits**, **1,727
  title↔company links**, with strong keys (`imdb_nconst` / `imdb_conmst`) and an entity-resolution
  log (`alias`, fuzzy matches parked for human review — never auto-merged).
- **IMDb enrichment** via the `imdbinfo` library: full department crew (DoP, sound, camera,
  art, costume, line producers…), production/sales/distribution companies, box office, awards,
  AKAs. IMDb-derived data stays local — **never published in `export/`**.

Zones depend one-way (Z2 reads Z1, never the reverse): adding messy landscape/corpus data can
never break grant queries or the document matrix.

## Consume it four ways

1. **SQLite** — query `build/kmi.db` directly (schema in `docs/STRUCTURE.md`).
2. **Prompt packs** — `build/prompt_packs/` (master digest, per-stream briefs, catalog, funding
   analytics) and the committed `export/` drop-in for other projects.
3. **RAG** — `build/embeddings/` (`make embed`; semantic search via `make rag-search SEARCH="…"`).
4. **MCP** — live querying from MCP clients (`make mcp`): 10 tools incl. `lookup_person`,
   `lookup_company`, `list_grants`, `get_document_spec`, `funding_stats`.

## Build it

```bash
# ingest sources -> data/staged / data/raw
make parse          # úthlutanir PDFs -> allocations            (needs pdftotext / poppler)
make kvik           # kvikmyndir.is series
make wiki-films     # Wikipedia Icelandic films
make producers      # SÍK member companies (producers.is)
make imdb-setup     # one-time: .venv-imdb + imdbinfo (needs uv)
make imdb-enrich    # full IMDb credits -> data/raw/imdb_full/

make build          # curated/*.json (+ IMDb fold) -> build/kmi.db   (stdlib only)
make packs          # build/kmi.db -> build/prompt_packs/
make publish        # rebuild + refresh the committed export/
```

Optional: `make embed-setup`/`make embed` (RAG, `.venv-rag`), `make mcp-setup`/`make mcp` (MCP).

## The dashboard

`make run` launches a read-only Streamlit dashboard over `build/kmi.db` (`.venv` with
streamlit+pandas): Overview · Grant browser · Document matrix · Funding explorer ·
Productions↔funding · People & companies · Amounts & rebate · Semantic search.

## Always verify official rules against
- https://www.kvikmyndamidstod.is/kvikmyndagerd/styrkir
- https://www.kvikmyndamidstod.is/kvikmyndagerd/leidbeiningar
- https://www.kvikmyndamidstod.is/kvikmyndagerd/umsoknarferlid
- https://www.kvikmyndamidstod.is/kvikmyndagerd/uthlutanir

Note the **application-max vs. disbursement-parts** distinction — see `docs/RECONCILIATION.md`.

---
The original integer-keyed MVP (CSV seed + sample Streamlit) is retired to
`archive/mvp-legacy/` and is not used by anything here.
