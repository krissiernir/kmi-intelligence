"""Fetch official KMÍ web pages into data/raw/html/ for provenance + reproducibility.

Saves each page as <slug>.html (raw) and <slug>.txt (extracted text), and prints a
content SHA-256 so sources.json can record it. The main kvikmyndamidstod.is site is
server-rendered, so plain HTTP fetch captures the content (the umsokn.* application
portal is login-gated and NOT fetchable).

Stdlib only. Run: python -m kmi_intelligence.ingest.fetch
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "raw" / "html"
SITE = ROOT / "data" / "raw" / "site"   # full sitemap mirror
BASE = "https://www.kvikmyndamidstod.is"
SITEMAP = BASE + "/sitemap.xml"

# slug -> path. Grant detail pages carry the authoritative CURRENT amounts/rules.
PAGES = {
    "styrkir": "/kvikmyndagerd/styrkir",
    "leidbeiningar": "/kvikmyndagerd/leidbeiningar",
    "umsoknarferlid": "/kvikmyndagerd/umsoknarferlid",
    "endurgreidslukerfi": "/kvikmyndagerd/endurgreidslukerfi",
    "handrit_leiknar": "/kvikmyndagerd/styrkir/handritsstyrkir-fyrir-leiknar-kvikmyndir",
    "handrit_sjonvarp": "/kvikmyndagerd/styrkir/handritsstyrkir-fyrir-leikid-sjonvarpsefni",
    "handrit_heimild_gamla": "/kvikmyndagerd/styrkir-gamla/handritsstyrkir-fyrir-heimildamyndir",
    "throun_framleidsla_leikid": "/kvikmyndagerd/styrkir/fyrir-leikid-efni-i-fullri-lengd-kvikmyndir-og-sjonvarpsthaetti",
    "framleidslustyrkir": "/kvikmyndagerd/styrkir/framleidslustyrkir",
    "framleidslustyrkir_skil": "/kvikmyndagerd/styrkir/framleidslustyrkir/skil-a-efni-vegna-framleidslustyrkja-og-vilyrda",
    "eftirvinnslustyrkir": "/kvikmyndagerd/styrkir/eftirvinnslustyrkir-fyrir-leiknar-kvikmyndir",
    "syningarstyrkir": "/kvikmyndagerd/styrkir/syningarstyrkir",
    "kvikmyndahatidir": "/kvikmyndagerd/styrkir/kvikmyndahatidir",
    "kynningar_ferdastyrkir": "/kvikmyndagerd/styrkir/kynningar-og-ferdastyrkir",
    "listraen_kvikmyndahus": "/kvikmyndagerd/styrkir/listraen-kvikmyndahus",
    "fagvidburdir": "/kvikmyndagerd/styrkir/styrkir-til-fagvidburda",
    "vinnustofur": "/kvikmyndagerd/styrkir/styrkir-til-thatttoku-i-vinnustofum",
    "adrir_sjodir": "/kvikmyndagerd/styrkir/adrir-sjodir-og-samframleidslusamningar",
}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = False

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(p.parts))


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "kmi-intelligence/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _slug(url: str) -> str:
    p = url.replace(BASE, "").strip("/")
    return (re.sub(r"[^a-z0-9]+", "_", p.lower()) or "index")[:120]


def fetch_sitemap() -> int:
    """Mirror EVERY URL in the sitemap into data/raw/site/ (.html + .txt) with a manifest.
    Polite (0.3s/req). Cached: skips a URL whose .html already exists."""
    from collections import Counter
    SITE.mkdir(parents=True, exist_ok=True)
    xml = get(SITEMAP)
    (SITE / "sitemap.xml").write_text(xml, encoding="utf-8")
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    print(f"{len(urls)} URLs in sitemap")
    manifest = []
    for i, url in enumerate(urls, 1):
        slug = _slug(url)
        section = (url.replace(BASE, "").strip("/").split("/") + ["index"])[0] or "index"
        f = SITE / f"{slug}.html"
        try:
            html = f.read_text(encoding="utf-8") if f.exists() else get(url)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {url}: {e}")
            continue
        if not f.exists():
            f.write_text(html, encoding="utf-8")
            (SITE / f"{slug}.txt").write_text(to_text(html), encoding="utf-8")
            time.sleep(0.3)
        manifest.append({"url": url, "slug": slug, "section": section,
                         "sha256": hashlib.sha256(html.encode()).hexdigest()[:16], "bytes": len(html)})
        if i % 40 == 0:
            print(f"  {i}/{len(urls)}")
    (SITE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {len(manifest)} pages -> {SITE.relative_to(ROOT)}")
    for s, n in Counter(m["section"] for m in manifest).most_common():
        print(f"  {s}: {n}")
    return 0


def main() -> int:
    if "--sitemap" in sys.argv:
        return fetch_sitemap()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{'slug':28} {'sha256[:16]':18} bytes")
    for slug, path in PAGES.items():
        url = BASE + path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kmi-intelligence/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print(f"{slug:28} ERROR {e}")
            continue
        (OUT / f"{slug}.html").write_text(html, encoding="utf-8")
        (OUT / f"{slug}.txt").write_text(to_text(html), encoding="utf-8")
        sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
        print(f"{slug:28} {sha[:16]}  {len(html)}")
    print(f"\nSaved {len(PAGES)} pages -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
