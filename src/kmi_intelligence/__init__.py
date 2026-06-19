"""kmi_intelligence — the KMÍ / Icelandic film-landscape knowledge base.

Pipeline modules:
  compile      curated/*.json (+ data/raw IMDb fold) -> build/kmi.db   (defines the schema)
  packs        build/kmi.db -> build/prompt_packs/
  rag          chunk + embed + cosine search (runs in .venv-rag)
  mcp_server   live MCP query server (runs in .venv-rag)
  ingest.*     source ingesters (see ingest/)

The legacy integer-keyed MVP (db/seed/readiness/analysis/prompt_builder) was retired to
archive/mvp-legacy/ — nothing here imports it.
"""

__all__ = ["compile", "packs", "rag", "mcp_server"]
