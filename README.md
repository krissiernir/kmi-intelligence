# kmi-intelligence

Local-first grant intelligence MVP for Icelandic film producers working with KMÍ (Kvikmyndamiðstöð Íslands) and Kvikmyndasjóður.

## What this tool is
`kmi-intelligence` is a producer dashboard that combines:
- grant categories,
- document requirements,
- evaluation criteria,
- sample allocation analysis,
- project readiness checks,
into one local SQLite + Streamlit workflow.

It is built to support better producer decisions, not just note-taking.

## Who it is for
- Icelandic film producers
- Producer teams preparing KMÍ applications
- Script/development/production teams needing structured grant intelligence

## MVP status (current)
This MVP includes:
- A normalized SQLite schema for grants, documents, criteria, allocations, projects, and source traceability.
- Seed loading from CSV with basic required-column validation.
- Streamlit pages:
  1. Home
  2. Grant Browser
  3. Document Matrix
  4. Allocation Explorer
  5. Project Readiness Checker
  6. AI Brief Builder (prompt generation only)

## What it does not do yet
- No web scraping pipeline yet.
- No PDF parsing pipeline yet.
- No AI API calls.
- No authentication or hosted deployment.
- No official legal/financial advice or official KMÍ scoring claims.

## Quickstart
```bash
python3 -m pip install -r requirements.txt
python3 -m src.kmi_intelligence.seed
streamlit run app/streamlit_app.py
```

Optional shortcuts:
```bash
make init
make seed
make run
```

## Data notes
- `data/seed` currently contains SAMPLE data.
- KMÍ URLs are official links, but many detailed values are placeholders and marked `sample` or `needs_verification`.
- Always verify official rules against:
  - https://www.kvikmyndamidstod.is/kvikmyndagerd/styrkir
  - https://www.kvikmyndamidstod.is/kvikmyndagerd/leidbeiningar
  - https://www.kvikmyndamidstod.is/kvikmyndagerd/umsoknarferlid
  - https://www.kvikmyndamidstod.is/kvikmyndagerd/uthlutanir
  - https://www.kvikmyndamidstod.is/kvikmyndagerd/uthlutanir/uthlutanir-fyrri-ara
