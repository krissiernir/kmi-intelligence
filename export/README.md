# KMÍ knowledge base — export (point other projects here)

Stable, committed, drop-in files describing **everything KMÍ funds and has funded**. Regenerated
with `make publish` from the canonical data in `../data/curated/`.

| File | Use it for |
|---|---|
| **`kmi_full.md`** (~40 KB) | The everything-pack: every grant + every document spec + amounts + rebate + criteria + process + funding. Paste as AI context. |
| **`kmi_full.json`** (~200 KB) | Same content, structured — load programmatically. |
| **`kmi_context.md`** (~3 KB) | Compact digest (grants table + rebate + funding headline). Use when context is tight. |

Each file is stamped with a generation date and a confidence legend. Amounts/deadlines are
guidance — verify on the live umsóknargátt before relying on them.

## How to use it in other projects

**1. Claude Project / claude.ai** — upload `kmi_full.md` as project knowledge. Ask "what documents do I need for a feature-film screenwriting grant, and what must each prove?"

**2. Claude Code / Cursor** — drop `kmi_full.md` in the repo (or reference this path) and `@`-mention it; or paste `kmi_context.md` into your system prompt.

**3. API (system prompt)** — load the file as a system/context message:
```python
ctx = open(".../export/kmi_full.md", encoding="utf-8").read()
messages = [{"role": "system", "content": "KMÍ reference:\n" + ctx}, ...]
```
(Use `kmi_context.md` if you're token-constrained; `kmi_full.json` if you want to inject specific fields.)

**4. Programmatic** — `json.load(open(".../export/kmi_full.json"))` → `streams`, `documents`, `criteria`, `amounts_disbursement`, `rebate`, `process`, `funding`. Or query `../build/kmi.db` directly with SQL.

**5. MCP (live, best for agents)** — instead of pasting files, let an MCP client query the DB live.
Tools: `list_grants`, `get_grant`, `get_document_spec`, `funding_stats`, `top_recipients`,
`get_rebate`, `search` (semantic). One-time: `make embed-setup && make embed && make mcp-setup`.
Config (already provided in `../.mcp.json` for Claude Code):
```json
{"mcpServers": {"kmi-intelligence": {
  "command": "<repo>/.venv-rag/bin/python",
  "args": ["-m", "kmi_intelligence.mcp_server"],
  "env": {"PYTHONPATH": "<repo>/src"}}}}
```

## Keeping it current
Edit `../data/curated/*.json` (with sources), then `make publish`. When KMÍ posts a new yearly
úthlutanir PDF, drop it in `../data/raw/uthlutanir/`, register it in `sources.json`, and `make publish`.
