# DATA MODEL (MVP)

SQLite tables:
1. sources
2. grants
3. documents
4. grant_document_requirements
5. criteria
6. grant_criteria
7. allocations
8. companies
9. people
10. projects
11. project_documents
12. applications

## Requirement level enum
- required
- recommended
- strategic
- conditional
- not_applicable
- unknown

## Notes
- All timestamps are stored as text (ISO-like in MVP).
- `confidence` should indicate data reliability (`sample`, `needs_verification`, or verified labels later).
- `source_id` ties claims back to origin for traceability.
- MVP keeps person/company linkage simple (text columns in projects/allocations), with dedicated tables reserved for future normalization.
