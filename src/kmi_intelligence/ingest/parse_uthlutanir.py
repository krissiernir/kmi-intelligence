"""Parse KMÍ úthlutanir (allocation) PDFs into staged allocation records.

Pipeline position: data/raw/uthlutanir/*.pdf  ->  data/staged/allocations.json
(see docs/ARCHITECTURE.md). Staged output is reviewed before it is trusted; the
compile step loads it into the `allocations` table with confidence handling.

Method: `pdftotext -layout` preserves column geometry. For each grant table we
derive column boundaries from its header row ("Verkefni / Handritshöfundur /
Leikstjóri / Umsækjandi / Styrkur / Samtals / Vilyrði ..."), then slice each
data row. Money tokens use Icelandic dot-grouping (130.000.000); bare years
(2024) lack dots, so the money regex ignores them and most prose.

Stdlib only (calls the `pdftotext` binary). Run: python -m kmi_intelligence.ingest.parse_uthlutanir
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "uthlutanir"
STAGED = ROOT / "data" / "staged"

YEARS = {
    2021: "src.uthlutanir_2021_pdf",
    2022: "src.uthlutanir_2022_pdf",
    2023: "src.uthlutanir_2023_pdf",
    2024: "src.uthlutanir_2024_pdf",
}

# at least one dot-group => >= 1.000; excludes bare years like 2024
MONEY = re.compile(r"\d{1,3}(?:\.\d{3})+")

FAMILY_HEADERS = [
    ("framleiðslustyrkir", ("framleidsla", None)),
    ("þróunarstyrkir", ("throun", None)),
    ("handritsstyrkir", ("handrit", None)),
    ("eftirvinnslustyrkir", ("eftirvinnsla", None)),
    ("kynningarstyrkir", ("annad", "kynning")),
    ("ferðastyrkir", ("annad", "ferd")),
    ("sjálfbærnistyrkir", ("annad", "sjalfbaerni")),
    ("sýningarstyrkir", ("annad", "syning")),
    ("aðrir styrkir", ("annad", "annad")),
]
FORMAT_HEADERS = [
    ("leiknar kvikmyndir", "leikin_kvikmynd"),
    ("leikið sjónvarpsefni", "leikid_sjonvarp"),
    ("leikið sjónvarp", "leikid_sjonvarp"),
    ("heimildamyndir", "heimildamynd"),
    ("heimildarmyndir", "heimildamynd"),
    ("stuttmyndir", "stuttmynd"),
]
TEXT_COLS = [
    ("project_title", "Verkefni"),
    ("writer", "Handritshöfundur"),
    ("director", "Leikstjóri"),
    ("applicant", "Umsækjandi"),
]


LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}


def extract_text(pdf: Path) -> str:
    # Keep ligatures here so character positions stay aligned for column slicing;
    # normalize them only when finalizing field values (see norm()).
    return subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    ).stdout


def norm(s: str) -> str:
    for lig, repl in LIGATURES.items():
        s = s.replace(lig, repl)
    return re.sub(r"\s+", " ", s).strip()


def money_tokens(line: str) -> list[tuple[int, int]]:
    """Return [(start_x, value), ...] for money tokens on a line."""
    return [(m.start(), int(m.group().replace(".", ""))) for m in MONEY.finditer(line)]


def detect_family(stripped: str):
    low = stripped.lower()
    for key, val in FAMILY_HEADERS:
        if low.startswith(key) or low == key.rstrip(":"):
            return val
    return None


def detect_format(stripped: str):
    low = stripped.lower()
    # only treat as a format header if it is a short heading, not a data row
    if len(stripped) > 60 and " - " not in stripped:
        return None
    for key, val in FORMAT_HEADERS:
        if low.startswith(key):
            return val
    return None


def header_anchors(header_line: str, block_above: list[str]):
    """Compute text-column boundaries + where the vilyrði (commitment) area starts."""
    cols = []
    for name, label in TEXT_COLS:
        i = header_line.find(label)
        if i != -1:
            cols.append((name, i))
    cols.sort(key=lambda c: c[1])
    if not cols:
        return None
    # vilyrði area begins after "Samtals" (or at first explicit "Vilyrði")
    search = " ".join(block_above + [header_line])
    vil_start = None
    vpos = header_line.find("Vilyrði")
    spos = header_line.find("Samtals")
    if spos == -1:
        for ln in block_above:
            p = ln.find("Samtals")
            if p != -1:
                spos = p
                break
    cands = []
    if vpos != -1:
        cands.append(vpos)
    if spos != -1:
        cands.append(spos + len("Samtals"))
    if cands:
        vil_start = min(cands)
    has_amount_col = ("Styrkur" in search) or (spos != -1)
    return {"cols": cols, "vil_start": vil_start, "has_amount_col": has_amount_col}


def slice_cell(line: str, start: int, end: int | None) -> str:
    return line[start:end].strip() if end else line[start:].strip()


def snap(line: str, pos: int, bound: int = 3) -> int:
    """Snap a header-derived column boundary to the nearest word start in THIS line.

    Tables sometimes indent the header row a space differently from data rows, which
    shifts every boundary by one and slices mid-word. We correct small drift only
    (<= bound chars), so genuinely empty cells (wide space runs) are left alone.
    """
    if pos <= 0:
        return 0
    if pos >= len(line):
        return len(line)
    if line[pos - 1] != " " and line[pos] != " ":  # mid-word: retreat to word start
        p, steps = pos, 0
        while p > 0 and line[p - 1] != " " and steps < bound:
            p -= 1
            steps += 1
        return p
    if line[pos] == " ":  # in padding: advance to cell start
        p, steps = pos, 0
        while p < len(line) and line[p] == " " and steps < bound:
            p += 1
            steps += 1
        return p
    return pos


def parse_year(text: str, year: int, source_id: str) -> list[dict]:
    lines = text.split("\n")
    records: list[dict] = []
    family = subtype = fmt = None
    anchors = None
    cur: dict | None = None
    generic = False  # aðrir/kynningar/ferða style (no Verkefni grid)

    def flush():
        nonlocal cur
        if cur is not None:
            finalize(cur)
            records.append(cur)
            cur = None

    def finalize(rec: dict):
        toks = sorted(rec.pop("_tokens", []), key=lambda t: (t[0], t[1]))
        vil_start = rec.pop("_vil_start", None)
        styrkur = [(ln, x, v) for (ln, x, v) in toks if vil_start is None or x < vil_start]
        vilyrdi = [(ln, x, v) for (ln, x, v) in toks if vil_start is not None and x >= vil_start]
        rec["amount_isk"] = styrkur[0][2] if styrkur else None
        rec["total_isk"] = styrkur[1][2] if len(styrkur) > 1 else None
        rec["commitments_json"] = json.dumps([v for _, _, v in vilyrdi], ensure_ascii=False)
        rec["commitment_isk"] = vilyrdi[0][2] if vilyrdi else None
        for k in ("project_title", "writer", "director", "applicant", "company", "producer"):
            if k in rec and isinstance(rec[k], str):
                rec[k] = norm(rec[k]) or None
        # split "Company / Person" applicant into company + producer
        app = rec.get("applicant")
        if app and " / " in app:
            comp, _, person = app.partition(" / ")
            rec["company"] = comp.strip()
            rec["producer"] = person.strip()
        elif app:
            rec["company"] = app

    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        fam = detect_family(stripped)
        if fam:
            flush()
            family, subtype = fam
            fmt = None
            anchors = None
            generic = family == "annad"
            continue

        f = detect_format(stripped)
        if f and ("Verkefni" not in line):
            flush()
            fmt = f
            anchors = None
            continue

        if "Verkefni" in line and "Handritshöfundur" in line:
            flush()
            block_above = [lines[i].rstrip() for i in range(max(0, idx - 2), idx)]
            anchors = header_anchors(line, block_above)
            generic = False
            continue

        # ----- data region -----
        if anchors:
            cols = anchors["cols"]
            toks = money_tokens(line)
            first_money_x = toks[0][0] if toks else None
            snapped = [snap(line, st) for _, st in cols]
            # The project column is leftmost: a real title begins at the row's first
            # text. Anchor col0 to that when it's near the title column (handles 1-letter
            # first words like "Á"/"Í" and drifted headers); far-right text => empty cell.
            lead = len(line) - len(line.lstrip())
            if abs(lead - cols[0][1]) <= 8:
                snapped[0] = lead
            cells = {}
            for ci, (name, _) in enumerate(cols):
                start = snapped[ci]
                end = snapped[ci + 1] if ci + 1 < len(cols) else first_money_x
                cells[name] = slice_cell(line, start, end)
            proj = cells.get("project_title", "")
            writer = cells.get("writer", "")
            applicant = cells.get("applicant", "")
            starts_row = bool(proj) and (bool(writer) or bool(applicant) or bool(toks))
            if starts_row:
                flush()
                cur = {
                    "year": year, "family": family, "subtype": subtype,
                    "format_track": fmt, "source_id": source_id,
                    "_tokens": [], "_vil_start": anchors["vil_start"], "raw_line": line.strip(),
                }
                for name in ("project_title", "writer", "director", "applicant"):
                    cur[name] = cells.get(name, "")
                cur["_tokens"].extend((idx, x, v) for x, v in toks)
            elif cur is not None:
                for name in ("project_title", "writer", "director", "applicant"):
                    extra = cells.get(name, "")
                    if extra:
                        cur[name] = (cur.get(name, "") + " " + extra).strip()
                cur["_tokens"].extend((idx, x, v) for x, v in toks)
            continue

        if generic:
            toks = money_tokens(line)
            if not toks or "kr." in line.lower():
                continue
            last_x, _ = toks[-1]
            # require the money to sit toward the right (a real row, not prose)
            if last_x < 40:
                continue
            flush()
            title = line[: toks[0][0]].strip()
            cur = {
                "year": year, "family": family, "subtype": subtype,
                "format_track": None, "source_id": source_id,
                "_tokens": [(idx, x, v) for x, v in toks], "_vil_start": None,
                "project_title": title, "applicant": None, "raw_line": line.strip(),
                "confidence": "low",
            }
            continue

    flush()
    # drop empties / header echoes
    return [r for r in records if r.get("project_title") and (r.get("amount_isk") or r.get("commitment_isk"))]


def main() -> int:
    STAGED.mkdir(parents=True, exist_ok=True)
    all_records: list[dict] = []
    per_year = {}
    for year, sid in YEARS.items():
        pdf = RAW / f"uthlutanir_{year}.pdf"
        if not pdf.exists():
            print(f"  skip {year}: {pdf} missing")
            continue
        recs = parse_year(extract_text(pdf), year, sid)
        for r in recs:
            r.setdefault("confidence", "needs_verification")
        all_records.extend(recs)
        total = sum(r["amount_isk"] or 0 for r in recs)
        per_year[year] = (len(recs), total)

    out = STAGED / "allocations.json"
    out.write_text(json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(all_records)} staged allocations -> {out.relative_to(ROOT)}")
    for year in sorted(per_year):
        n, tot = per_year[year]
        print(f"  {year}: {n:3} rows   styrkur total = {tot:>15,} ISK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
