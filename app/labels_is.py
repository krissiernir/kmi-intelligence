"""Icelandic UI labels for the KMÍ dashboard — relabel proposal (STAGED).

Lexicon-grounded (see ../lexicon/). The app (kmi-intelligence/app/streamlit_app.py) is the
main agent's file and was edited today — so this is staged, not wired in. To apply: import this
and replace each English literal with t("key"), or hand it to the main agent.

A few terms are coinages / brand choices — marked `# confirm`. Kristján (producer) should bless
the wording before it ships; that's the "terms that actually apply to Icelandic productions" part.
"""

IS = {
    # ── sidebar / navigation ──
    "brand": "Bíómonsi",                           # named by Kristján 🎬 (the app's name)
    "nav_label": "Síða",
    "nav_overview": "📊 Yfirlit",
    "nav_grants": "🎬 Skoða styrki",               # authentic — KMÍ's own wording
    "nav_docs": "📋 Skjalakröfur",
    "nav_funding": "💰 Úthlutanir",
    "nav_productions": "🎞️ Framleiðslur og úthlutanir",
    "nav_people": "🧑‍🎬 Fólk og fyrirtæki",
    "nav_amounts": "📐 Upphæðir og endurgreiðsla",
    "nav_search": "🔎 Merkingarleit",              # confirm: 'Merkingarleit' vs 'Snjallleit' vs simply 'Leit'
    "sidebar_caption": "Skrifvarið yfir gagnagrunni. Endurbyggt með `make all`.",

    # ── Overview / Yfirlit ──
    "ov_title": "Bíómonsi — mælaborð framleiðanda",
    "ov_caption": "Gagnagrunnur með rekjanlegum heimildum um styrki KMÍ og úthlutanir (2021–2024).",
    "ov_streams": "Styrkjaflokkar (gáttir)",
    "ov_docs": "Skjalakröfur",
    "ov_awards": "Úthlutanir 2021–2024",
    "ov_total": "Heildarúthlutun",
    "ov_by_year": "Úthlutað eftir árum",

    # ── Grant browser / Skoða styrki ──
    "gb_title": "Skoða styrki",
    "gb_family": "Flokkur",
    "gb_stream": "Styrkur (gátta)",
    "gb_max": "Hámark umsóknar",
    "gb_scope": "fer eftir umfangi",
    "gb_stage": "Þrep",
    "gb_gatta": "Gátta-auðkenni",
    "gb_apply": "Sækja um:",
    "gb_rules": "Skilyrði:",
    "gb_docs": "Fylgigögn",
    "gb_confidence": "Áreiðanleiki",
    "gb_sources": "heimildir",

    # ── Document matrix / Skjalakröfur ──
    "dm_title": "Skjalakröfur",
    "dm_family": "Flokkur",
    "dm_req": "Krafa",
    "dm_count": "{n} kröfur",

    # ── Funding explorer / Úthlutanir ──
    "fe_title": "Úthlutanir 2021–2024",
    "fe_years": "Ár",
    "fe_family": "Flokkur",
    "fe_company": "Fyrirtæki inniheldur",
    "fe_awards": "Úthlutanir",
    "fe_total": "Heildarstyrkur",
    "fe_median": "Miðgildi styrks",
    "fe_by_family": "Eftir flokkum",
    "fe_top_companies": "Efstu fyrirtæki",
    "fe_table": "Úthlutanir",

    # ── People & companies / Fólk og fyrirtæki ──
    "pc_title": "Fólk og fyrirtæki",
    "pc_lookup": "Fletta upp",
    "pc_person": "Einstaklingur",
    "pc_company": "Fyrirtæki",
    "pc_person_name": "Nafn einstaklings",
    "pc_company_name": "Nafn fyrirtækis",
    "pc_none": "Engin niðurstaða.",
    "pc_roles": "Hlutverk",
    "pc_credits": "skráningar",
    "pc_filmography": "Verkaskrá",
    "pc_collaborators": "Tíðir samstarfsmenn",
    "pc_sik": "SÍK-félagi",
    "pc_grants": "styrkir",
    "pc_funded_projects": "Styrkt verkefni",
    "pc_merge": "Sameiningartillögur (bíða yfirferðar)",

    # ── Amounts & rebate / Upphæðir og endurgreiðsla ──
    "ar_title": "Upphæðir og endurgreiðsla",
    "ar_maxima": "Hámarksupphæðir (eftir gátt)",
    "ar_history": "Úthlutunarsaga (orðrétt úr PDF)",
    "ar_rebate": "Endurgreiðsla",
    "ar_general": "almenn",
    "ar_enhanced": "aukin",
    "ar_process": "Umsóknar- og skilaferli",

    # ── Productions ↔ funding / Verk og úthlutanir ──
    "pf_title": "Framleiðslur ↔ úthlutanir KMÍ",
    "pf_titles": "Framleiðslur",
    "pf_matched": "Með úthlutun",
    "pf_unfunded": "Líklega óstyrkt (2022+)",
    "pf_gap": "Utan skrár (fyrir 2021)",
    "pf_kind": "Tegund",
    "pf_status": "Tengistaða",
    "pf_from_year": "Frá ári",

    # ── Semantic search / Merkingarleit ──
    "ss_title": "Merkingarleit (RAG)",
    "ss_prompt": "Spyrðu á íslensku eða ensku",
    "ss_results": "Niðurstöður",
    "ss_search": "Leita",
}

# Grant families — Icelandic only (app currently shows "Handrit (screenwriting)" etc.)
FAMILY_IS = {
    "handrit": "Handrit", "throun": "Þróun", "framleidsla": "Framleiðsla",
    "eftirvinnsla": "Eftirvinnsla", "endurgreidsla": "Endurgreiðsla", "annad": "Aðrir",
}

# Document requirement levels
LEVEL_IS = {
    "required": "Krafist", "newcomer": "Nýliði", "recommended": "Mælt með",
    "strategic": "Stefnumótandi", "optional": "Valkvætt",
}

# Production ↔ ledger cross-reference status
XREF_IS = {
    "matched": "með úthlutun", "likely_unfunded": "líklega óstyrkt", "ledger_gap": "utan skrár",
}

# Kind of work
KIND_IS = {"All": "Allt", "film": "kvikmynd", "series": "þáttaröð"}


def t(key: str, default: str = "") -> str:
    """Look up an Icelandic label; falls back to default (or the key) if missing."""
    return IS.get(key, default or key)
