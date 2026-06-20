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
from datetime import UTC

__all__ = ["compile", "packs", "rag", "mcp_server", "log_event"]


def log_event(action: str, **fields) -> None:
    """Append one timestamped JSON line to logs/activity.jsonl — a cheap audit of what we pull/do.

    Stdlib only, O(1) append, a few bytes per call. Never raises (logging must not break a run).
    Usage:  from kmi_intelligence import log_event;  log_event("ingest.klapptre", posts=1705)
    """
    try:
        import json
        from datetime import datetime, timezone
        from pathlib import Path
        rec = {"ts": datetime.now(UTC).isoformat(timespec="seconds"),
               "action": action, **fields}
        log = Path(__file__).resolve().parents[2] / "logs" / "activity.jsonl"
        log.parent.mkdir(exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
