"""Clean WordPress article HTML → information-dense plain text (drops repetitive boilerplate).

The Klapptré REST API already returns just the post body (no site chrome). This removes the
remaining in-body junk: WP shortcodes, photo-credit captions, and — data-driven — any sentence
that recurs across many articles (methodology footers, source pointers, standard sign-offs are
boilerplate by definition). HTML tables are preserved as `cell | cell` rows so the box-office /
viewership numbers stay parseable.

Used by the Zone 3 corpus build. Stdlib only.
"""
from __future__ import annotations

import html as _html
import re
from collections import Counter

_SHORTCODE = re.compile(r"\[/?[^\]]+\]")
_CAPTION = re.compile(r"<figcaption.*?</figcaption>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
# photo-credit / source lines that are pure chrome
_CREDIT = re.compile(r"^\s*(mynd|ljósmynd|skjáskot|aðsend mynd)\s*[:/].*$", re.I)


def to_text(content_html: str) -> str:
    """Body HTML -> plain text, keeping table rows as 'a | b | c' and paragraphs as lines."""
    h = content_html or ""
    h = _CAPTION.sub(" ", h)            # drop image captions (photo credits)
    h = _SHORTCODE.sub(" ", h)          # drop [usr]/[tble]/[column]… shortcodes
    h = re.sub(r"</t[dh]>", " | ", h, flags=re.I)
    h = re.sub(r"</tr>|</p>|<br\s*/?>|</h\d>|</li>", "\n", h, flags=re.I)
    t = _TAG.sub("", h)
    t = _html.unescape(t)
    lines = []
    for ln in t.splitlines():
        ln = re.sub(r"\s*\|\s*", " | ", ln).strip(" |\t ")
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln and not _CREDIT.match(ln):
            lines.append(ln)
    return "\n".join(lines)


def boilerplate_fragments(texts, min_docs: int = 8) -> set[str]:
    """Sentences appearing in >= min_docs distinct articles = boilerplate to drop."""
    df = Counter()
    for t in texts:
        seen = set()
        for s in re.split(r"(?<=[.!?])\s+|\n", t):
            s = s.strip()
            if 15 < len(s) < 220:
                seen.add(s)
        df.update(seen)
    return {s for s, n in df.items() if n >= min_docs}


def strip_boilerplate(text: str, fragments: set[str]) -> str:
    if not fragments:
        return text
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n", text):
        if s.strip() not in fragments:
            out.append(s)
    return "\n".join(x for x in (l.strip() for l in out) if x)
