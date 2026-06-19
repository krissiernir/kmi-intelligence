"""RAG layer: chunk the knowledge base, then embed with a pluggable backend.

Design (per the chosen approach): the CHUNKER is backend-agnostic and stdlib-only;
the EMBEDDER is a thin pluggable interface you point at any model later.

  build/embeddings/
    chunks.jsonl     one line per chunk: {id, text, metadata{...}}
    index.jsonl      chunks + their vectors (written by `embed`)

Backends (registry below):
  hash    dependency-free LEXICAL placeholder (bag-of-words hashed) — runs out of the
          box so the pipeline works; NOT semantic. Replace before relying on results.
  local   sentence-transformers multilingual model (optional dep)
  openai  OpenAI text-embedding-3 (needs OPENAI_API_KEY)
  voyage  Voyage multilingual (needs VOYAGE_API_KEY)

CLI:
  python -m kmi_intelligence.rag chunk
  python -m kmi_intelligence.rag embed  [--backend hash|local|openai|voyage]
  python -m kmi_intelligence.rag search "norræn meðframleiðsla heimildamynd" [--backend ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "kmi.db"
OUT = ROOT / "build" / "embeddings"
CHUNKS = OUT / "chunks.jsonl"
INDEX = OUT / "index.jsonl"
HASH_DIM = 512


# ---------------- chunking (backend-agnostic) ----------------
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def build_chunks() -> int:
    c = _conn()
    OUT.mkdir(parents=True, exist_ok=True)
    chunks = []

    for s in c.execute("SELECT * FROM grant_streams"):
        docs = [r["document_text"] for r in c.execute(
            "SELECT document_text FROM stream_documents WHERE stream_id=? AND requirement_level='required'", (s["id"],))]
        rules = "; ".join(f"{k}: {v}" for k, v in json.loads(s["rules_json"] or "{}").items())
        text = (f"{s['name_is']} ({s['gatta_id']}) — {s['family']}/{s['stage']}. "
                f"Markmið: {s['purpose'] or ''}. "
                f"Hámarksupphæð: {s['max_amount_isk'] or 'óþekkt'}. "
                f"Greiðsluskipting: {s['payment_split'] or '—'}. "
                f"{('Skilyrði: ' + rules + '. ') if rules else ''}"
                f"Skylt fylgigögn: {', '.join(docs)}.")
        chunks.append({"id": f"stream:{s['id']}", "text": text,
                       "metadata": {"type": "grant_stream", "gatta_id": s["gatta_id"],
                                    "family": s["family"], "stage": s["stage"],
                                    "confidence": s["confidence"]}})

    r = c.execute("SELECT * FROM rebate").fetchone()
    if r:
        chunks.append({"id": "rebate", "text":
            f"Endurgreiðslukerfi: {r['general_pct']}% almennt ({r['general_basis']}), "
            f"{r['enhanced_pct']}% sérstakt ({r['enhanced_conditions']}). {r['regla_18_manuda']}",
            "metadata": {"type": "rebate", "confidence": r["confidence"]}})

    for st in c.execute("SELECT * FROM process_stages ORDER BY ord"):
        chunks.append({"id": f"process:{st['id']}", "text":
            f"Samningsferli – {st['name_is']}: {st['condition'] or ''} "
            f"{('Frestur: ' + str(st['deadline_months']) + ' mán.') if st['deadline_months'] else ''}",
            "metadata": {"type": "process_stage"}})

    for d in c.execute("SELECT * FROM documents"):
        chunks.append({"id": f"doc:{d['doc_key']}", "text":
            f"Skjal/fylgigagn: {d['name_is']} ({d['name_en']}). Tilgangur: {d['purpose']} "
            f"Á að sanna: {d['what_it_must_prove']} Snið/lengd: {d['format_limit']}. "
            f"Skráarnafn: {d['naming_convention']}. Algeng mistök: {d['common_weaknesses']}",
            "metadata": {"type": "document", "doc_key": d["doc_key"]}})

    for cr in c.execute("SELECT * FROM criteria"):
        chunks.append({"id": f"criterion:{cr['id']}", "text":
            f"Matsþáttur ráðgjafa: {cr['name_is']} ({cr['name_en']}). {cr['description']} "
            f"Styrkleikamerki: {cr['evidence_examples']} Rauð flögg: {cr['red_flags']}",
            "metadata": {"type": "criterion", "id": cr["id"]}})

    # ledger: one chunk per real award (for "find similar funded projects")
    for a in c.execute("SELECT * FROM allocations WHERE amount_isk IS NOT NULL"):
        text = (f"{a['project_title']} ({a['year']}) — {a['family']} "
                f"{a['format_track'] or ''}. Framleiðandi: {a['company'] or a['applicant'] or '—'}. "
                f"Leikstjóri: {a['director'] or '—'}. Handritshöfundur: {a['writer'] or '—'}. "
                f"Styrkur: {a['amount_isk']:,} ISK.")
        chunks.append({"id": f"alloc:{a['id']}", "text": text,
                       "metadata": {"type": "allocation", "year": a["year"], "family": a["family"],
                                    "format_track": a["format_track"], "company": a["company"],
                                    "amount_isk": a["amount_isk"], "confidence": a["confidence"]}})

    with open(CHUNKS, "w", encoding="utf-8") as fh:
        for ch in chunks:
            fh.write(json.dumps(ch, ensure_ascii=False) + "\n")
    print(f"Wrote {len(chunks)} chunks -> {CHUNKS.relative_to(ROOT)}")
    return len(chunks)


# ---------------- pluggable embedders ----------------
def _tokenize(s: str):
    return [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in s).split() if len(t) > 1]


# Each backend takes (texts, kind) where kind is "passage" (documents, at index time)
# or "query" (at search time). Some models embed the two asymmetrically.
import os

LOCAL_MODEL = os.environ.get("KMI_EMBED_MODEL", "intfloat/multilingual-e5-base")
_model_cache: dict = {}


def embed_hash(texts, kind="passage"):
    """Dependency-free LEXICAL placeholder. Not semantic — for plumbing/tests only."""
    out = []
    for t in texts:
        v = [0.0] * HASH_DIM
        for tok in _tokenize(t):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % HASH_DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def embed_local(texts, kind="passage"):
    """Local multilingual sentence-transformers (default: intfloat/multilingual-e5-base).
    Free, private, offline. e5 models require 'query:'/'passage:' prefixes."""
    from sentence_transformers import SentenceTransformer  # optional dep
    model = _model_cache.get(LOCAL_MODEL)
    if model is None:
        model = _model_cache[LOCAL_MODEL] = SentenceTransformer(LOCAL_MODEL)
    if "e5" in LOCAL_MODEL.lower():
        prefix = "query: " if kind == "query" else "passage: "
        texts = [prefix + t for t in texts]
    return model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()


def embed_openai(texts, kind="passage"):
    from openai import OpenAI  # optional dep
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.embeddings.create(model="text-embedding-3-large", input=texts)
    return [d.embedding for d in resp.data]


def embed_voyage(texts, kind="passage"):
    import voyageai  # optional dep
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    input_type = "query" if kind == "query" else "document"
    return client.embed(texts, model="voyage-3", input_type=input_type).embeddings


EMBEDDERS = {"hash": embed_hash, "local": embed_local, "openai": embed_openai, "voyage": embed_voyage}


def build_index(backend: str) -> int:
    if not CHUNKS.exists():
        build_chunks()
    rows = [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines()]
    embed = EMBEDDERS[backend]
    vectors = embed([r["text"] for r in rows], "passage")
    meta = {"_backend": backend, "_dim": len(vectors[0])}
    if backend == "local":
        meta["_model"] = LOCAL_MODEL
    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta) + "\n")
        for r, v in zip(rows, vectors):
            fh.write(json.dumps({**r, "vector": v}, ensure_ascii=False) + "\n")
    note = "  (LEXICAL placeholder — swap in a real backend before relying on it)" if backend == "hash" else ""
    print(f"Embedded {len(rows)} chunks with backend '{backend}' -> {INDEX.relative_to(ROOT)}{note}")
    return len(rows)


def search(query: str, backend: str, k: int = 5) -> list[dict]:
    rows = [json.loads(l) for l in INDEX.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if "vector" in r]
    qv = EMBEDDERS[backend]([query], "query")[0]

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalized
    scored = sorted(((cos(qv, r["vector"]), r) for r in rows), key=lambda x: -x[0])[:k]
    return [{"score": round(s, 4), "id": r["id"], "type": r["metadata"].get("type"),
             "text": r["text"], "metadata": r["metadata"]} for s, r in scored]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["chunk", "embed", "search"])
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--backend", default="hash", choices=list(EMBEDDERS))
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="emit results as one JSON line")
    a = ap.parse_args()
    if not DB_PATH.exists():
        print("build/kmi.db not found — run `make build` first.")
        return 1
    if a.cmd == "chunk":
        build_chunks()
    elif a.cmd == "embed":
        build_index(a.backend)
    elif a.cmd == "search":
        if not INDEX.exists():
            build_index(a.backend)
        results = search(a.query, a.backend, a.k)
        if a.json:
            print(json.dumps(results, ensure_ascii=False))
        else:
            print(f"\nTop {a.k} for: {a.query!r}  (backend={a.backend})\n")
            for r in results:
                print(f"  {r['score']:.3f}  [{r['type']}] {r['text'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
