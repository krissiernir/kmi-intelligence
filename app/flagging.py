"""Inline data-flagging — the 4th trust layer for Bíómonsi.

While browsing, the user flags a row/entity as wrong / missing / review. Each flag is appended as one
JSON line to an append-only queue (like the activity log). The import/pipeline agent consumes the queue,
acts, and writes status="resolved". This module NEVER writes to build/kmi.db.

Queue schema (frozen — shared contract with the consumer agent; see BUILD_BRIEF.md):
    {"id","ts","user","target_type","target_id","target_label","flag","note","status","resolution"}

STAGED — review + test before deploy.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from pathlib import Path

# Icelandic flag labels
FLAGS = {"wrong": "Rangt", "missing": "Vantar", "review": "Til skoðunar"}


def default_queue_path() -> Path:
    """logs/review_queue.jsonl next to the activity log, overridable via KMI_REVIEW_QUEUE."""
    env = os.environ.get("KMI_REVIEW_QUEUE")
    if env:
        return Path(env)
    # when deployed at kmi-intelligence/app/flagging.py → repo root is parents[1]
    return Path(__file__).resolve().parents[1] / "logs" / "review_queue.jsonl"


def record_flag(target_type: str, target_id, target_label: str, flag: str,
                note: str = "", user: str = "kristjan",
                queue_path: Path | None = None) -> dict:
    """Append one flag to the queue. Returns the written record."""
    if flag not in FLAGS:
        raise ValueError(f"flag must be one of {list(FLAGS)}")
    path = Path(queue_path) if queue_path else default_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": f"{_dt.datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}",
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "user": user,
        "target_type": target_type,
        "target_id": str(target_id),
        "target_label": target_label,
        "flag": flag,
        "note": note.strip(),
        "status": "open",
        "resolution": None,
    }
    with open(path, "a", encoding="utf-8") as fh:           # append = atomic enough for one writer
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_flags(queue_path: Path | None = None) -> list[dict]:
    path = Path(queue_path) if queue_path else default_queue_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def summary(queue_path: Path | None = None) -> dict:
    """Counts for `make health`: total, open, by flag-type."""
    flags = load_flags(queue_path)
    open_ = [f for f in flags if f.get("status") == "open"]
    by_type: dict[str, int] = {}
    for f in open_:
        by_type[f["flag"]] = by_type.get(f["flag"], 0) + 1
    return {"total": len(flags), "open": len(open_), "open_by_type": by_type}


# ───────────────────────── Streamlit widget ─────────────────────────
def flag_button(st, target_type: str, target_id, target_label: str,
                queue_path: Path | None = None, key: str | None = None) -> None:
    """A 🚩 popover with Rangt / Vantar / Til skoðunar + a note. Drop on any row/entity view."""
    key = key or f"flag_{target_type}_{target_id}"
    container = st.popover("🚩 Merkja", help="Merkja gögn sem röng, vantar, eða til skoðunar") \
        if hasattr(st, "popover") else st.expander("🚩 Merkja")
    with container:
        st.caption(f"Merki: **{target_label}**")
        note = st.text_input("Athugasemd (valfrjálst)", key=f"{key}_note")
        cols = st.columns(len(FLAGS))
        for col, (code, label) in zip(cols, FLAGS.items()):
            if col.button(label, key=f"{key}_{code}", use_container_width=True):
                record_flag(target_type, target_id, target_label, code, note, queue_path=queue_path)
                st.toast(f"Merkt: {label} — {target_label}", icon="🚩")


# ───────────────────────── CLI (consumer convenience) ─────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "open":
        for f in load_flags():
            if f.get("status") == "open":
                print(f"{f['ts']}  {f['flag']:7}  {f['target_type']}:{f['target_label']}  — {f['note']}")
    else:
        print(json.dumps(summary(), ensure_ascii=False, indent=2))
