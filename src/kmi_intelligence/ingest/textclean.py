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
    h = (content_html or "").replace("\xad", "")  # drop soft hyphens (KMÍ titles use them)
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


# ── Icelandic NLP (Miðeind: BÍN morphology + Greynir NER) ──────────────────────────────
# LAZY + GRACEFUL: islenska/reynir live only in .venv-nlp. When absent (e.g. the stdlib core
# build), every function degrades to identity/empty so nothing breaks. Singletons are cached.
_NAME_PARTS = {"ism", "erm", "föð", "móð", "gæl"}  # BÍN 'hluti' tags for person-name pieces
_bin = _greynir = None
_bin_off = _greynir_off = False


def _get_bin():
    global _bin, _bin_off
    if _bin is None and not _bin_off:
        try:
            from islenska import Bin
            _bin = Bin()
        except Exception:
            _bin_off = True
    return _bin


def _get_greynir():
    global _greynir, _greynir_off
    if _greynir is None and not _greynir_off:
        try:
            from reynir import Greynir
            _greynir = Greynir()
        except Exception:
            _greynir_off = True
    return _greynir


def nlp_available() -> bool:
    return _get_bin() is not None


def lemma(word: str) -> str:
    """Inflected Icelandic word -> lemma (styrkjum -> styrkur). Identity if NLP unavailable."""
    b = _get_bin()
    if not b or not word:
        return word
    try:
        res = b.lookup(word)
        return res[1][0].ord if res[1] else word
    except Exception:
        return word


def lemmas(word: str) -> list[str]:
    """ALL candidate lemmas for an inflected word — for lexical indexing/expansion, where an
    ambiguous form ('styrkjum' = noun styrkur OR verb styrkja) must carry every reading so a query
    on any of them matches. Falls back to [word]. (Use lemma() when you want a single best lemma.)"""
    b = _get_bin()
    if not b or not word:
        return [word] if word else []
    try:
        res = b.lookup(word)
        return sorted({e.ord for e in res[1]}) or [word.lower()]
    except Exception:
        return [word.lower()]


def normalize_name(s: str) -> str:
    """Person/proper name in any case -> nominative (Baltasars Kormáks -> Baltasar Kormákur).

    Prefers BÍN person-name lemmas (hluti ∈ ism/erm/föð/…); falls back to the first lemma, then the
    token. Returns the input unchanged when NLP is unavailable. Not perfect on rare names (fuzzy
    match downstream absorbs the residue)."""
    b = _get_bin()
    if not b or not s:
        return s
    out = []
    for tok in s.split():
        try:
            res = b.lookup(tok)
            names = [e.ord for e in res[1] if getattr(e, "hluti", "") in _NAME_PARTS]
            out.append(names[0] if names else (res[1][0].ord if res[1] else tok))
        except Exception:
            out.append(tok)
    return " ".join(out)


def entities(text: str) -> list[str]:
    """Person/proper-noun mentions in `text`, returned in NOMINATIVE via Greynir NER.
    Empty list if NLP unavailable. Good for content/term extraction + mention-linkage."""
    g = _get_greynir()
    if not g or not text:
        return []
    try:
        s = g.parse_single(text)
        return list(s.tree.persons) if (s and s.tree is not None) else []
    except Exception:
        return []
