# Amount reconciliation — curated catalog vs. authoritative sources

**Date:** 2026-06-19.

## The key distinction (this caused one wrong turn — documented honestly)
There are **two different "amounts"** for screenwriting/development grants, and they must
not be conflated:

1. **Application maximum (Hámarksupphæð)** — the most you can request per gátta. Lives on
   the live **styrkir detail pages** → now in `grant_streams.max_amount_isk`.
2. **Disbursement structure (hlutar)** — how an *awarded* grant is paid out in progress-based
   installments, reported per year in the **úthlutanir PDFs** → in `grant_amounts` (table +
   `grant_amounts.json`).

Example (feature screenwriting): the **max** is 1.5M (I) / 1.5M (II) / 3.0M (I+II), but the
2023 **disbursement** parts were 600k / 1.0M / 1.4M. Both are correct; they describe different
things. My first pass mistook the disbursement prose for the cap and wrongly lowered the maxima
— corrected after fetching the live detail pages (`data/raw/html/`).

## Authoritative current maxima (live styrkir detail pages, verified)
| Gátta | Stream | max_amount_isk | Source |
|---|---|---|---|
| CUPCLS | Leikin – Handrit I | 1.500.000 | handrit_leiknar |
| UHPP3T | Leikin – Handrit II | 1.500.000 | handrit_leiknar |
| MFLH1S | Leikin – Handrit I+II | 3.000.000 | handrit_leiknar |
| RGQHHO | Sjónvarp – Handrit I | 1.500.000 | handrit_sjonvarp |
| WFBYW2 | Sjónvarp – Handrit II | 1.500.000 | handrit_sjonvarp |
| 2D61HS | Sjónvarp – Handrit III | 3.000.000 | handrit_sjonvarp |
| UJDT4B/K7BJJS | Leikin – Þróun I/II | scope-dependent (null) | throun_framleidsla_leikid |
| XSLQ7F/FLQNR7 | Sjónvarp – Þróun I/II | scope-dependent (null) | throun_framleidsla_leikid |
| LGTO9C/O0NL3H/HRBZFP/RYXIIO | Framleiðsla (all) | scope-dependent (null) | framleidslustyrkir |
| DLP87P | Leikin – Eftirvinnsla | 15.000.000 | eftirvinnslustyrkir |
| VV0GSX | Heimild – Handrit | 600.000 (needs_verification) | úthl. 2024 / gamla page conflict |

Note: total screenwriting support per project is capped at **3.0M**. Development grants are
"Upphæð fer eftir umfangi verkefnis" (scope-dependent); the 2. þróunarstyrkur is only for
projects that already hold a production-grant vilyrði.

## Disbursement history (úthlutanir PDFs → `grant_amounts`, verified verbatim)
| Family / format | Structure | Amounts | Latest source |
|---|---|---|---|
| handrit / leikin | 3 hlutar | 500k/900k/1.2M (2021–22) → 600k/1.0M/1.4M (2023) | úthl. 2023 l448 |
| handrit / sjónvarp | 3 hlutar | 500k/1.2M/900k (2021–22) → 600k/1.4M/1.0M (2023–24) | úthl. 2024 l546 |
| handrit / heimild | 1 þrep | 500k (2021–22) → 600k (2023–24) | úthl. 2024 l683 |
| throun / leikin & sjónvarp | 2 hlutar | 2.5M / 3.5M | úthl. 2023 |
| throun / heimild | frekari þróun | 5.0M | úthl. 2023 |

## Rebate (live endurgreiðslukerfi page, verified)
25% general; **35%** requires ALL of: (1) ≥350M ISK domestic spend, (2) ≥10 principal-photography
days + ≥30 combined shoot/post days in Iceland, (3) ≥50 staff working directly on the production
in Iceland. Partial payout once ≥50% of budget is paid in Iceland. (Earlier curated text said
only "30 tökudagar / unspecified" — now corrected.)

## Still unverifiable from public sources
- **Heimild – Handrit (VV0GSX):** úthlutanir 2024 says 600k; the *old* `styrkir-gamla` page says
  1.5M. No current public heimild screenwriting page exists → kept at 600k, `needs_verification`.
- Exact 2025/2026 figures (no newer úthlutanir PDF published at check time).
- Per-gátta amounts behind the login-gated application portal (umsokn.*) are not fetchable.
