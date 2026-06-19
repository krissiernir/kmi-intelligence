"""Ingest the SÍK member registry (producers.is félagaskrá) → staged companies.

producers.is = Samband íslenskra kvikmyndaframleiðenda (Association of Icelandic Film Producers),
a Joomla site. /felagaskra is the authoritative member directory of Icelandic production
companies — the canonical anchor for company entity resolution (Zone 2). Each member: name,
address, phone, website, email.

Stdlib only. Run: python -m kmi_intelligence.ingest.producers_is
"""
from __future__ import annotations

import html as ihtml
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "producers"
STAGED = ROOT / "data" / "staged" / "companies_producers.json"
URL = "https://producers.is/index.php/felagaskra"
UA = {"User-Agent": "kmi-intelligence/1.0 (research; cross-reference with public KMÍ grant data)"}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _clean(s: str) -> str:
    return ihtml.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def parse(html: str) -> list[dict]:
    names = re.findall(r'class="memberfirmname"[^>]*>(.*?)</h2>', html, flags=re.S)
    texts = re.findall(r'class="memberfirmtext"[^>]*>(.*?)</p>', html, flags=re.S)
    out = []
    for n_raw, t_raw in zip(names, texts):
        name = _clean(n_raw)
        if not name:
            continue
        # capture links from the raw HTML block (href) before stripping tags
        website = next((u for u in re.findall(r'https?://[^"\'<> ]+', t_raw)
                        if "producers.is" not in u and "schema.org" not in u), None)
        text = _clean(t_raw)
        email = (re.search(r"[\w.\-]+@[\w.\-]+\.\w+", text) or [None])
        email = email.group(0) if hasattr(email, "group") else None
        phone = re.search(r"\b\d{7}\b", text)
        if not website:
            website = next((u for u in re.findall(r'https?://[^\s]+', text) if "producers.is" not in u), None)
        # address = text with email/phone/website stripped
        addr = text
        for token in filter(None, [email, phone.group(0) if phone else None, website]):
            addr = addr.replace(token, " ")
        out.append({
            "name": name,
            "type": "production",
            "is_sik_member": True,
            "website": website,
            "email": email,
            "phone": phone.group(0) if phone else None,
            "address": re.sub(r"\s+", " ", addr).strip(" ,") or None,
            "source": "src.producers_is",
        })
    return out


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    html = get(URL)
    (RAW / "felagaskra.html").write_text(html, encoding="utf-8")
    companies = parse(html)
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    STAGED.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Parsed {len(companies)} SÍK member companies -> {STAGED.relative_to(ROOT)}")
    for c in companies[:5]:
        print(f"  {c['name']:32} {c.get('website') or '':28} {c.get('email') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
