# archive/mvp-legacy — retired MVP (do not use)

The original integer-keyed MVP, kept only for history. **Nothing in the live project imports
or runs this.** The current system is the text-keyed knowledge base built by
`src/kmi_intelligence/compile.py` → `build/kmi.db` (see `docs/ARCHITECTURE.md`, `docs/STRUCTURE.md`).

| Retired | Replaced by |
|---|---|
| `code/db.py`, `code/seed.py` (SQLAlchemy-ish sample schema + CSV seed) | `compile.py` (TEXT-keyed schema, curated/*.json) |
| `code/readiness.py`, `code/analysis.py`, `code/prompt_builder.py` | `packs.py`, `rag.py`, `mcp_server.py` |
| `code/test_seed_load.py` | — (no longer applicable) |
| `seed_csv/*.csv` (sample data) | `data/curated/*.json` (source of truth) |
| old `db/kmi.db` (integer-keyed sample) | `build/kmi.db` (generated, gitignored) |

To resurrect for reference, run from the repo root with `PYTHONPATH=archive/mvp-legacy/code`.
