# AGENTS instructions for kmi-intelligence

Scope: entire repository.

1. Preserve source traceability
- Never store grant rules, deadlines, amounts, or eligibility claims without a traceable source.
- For extracted facts, keep: source URL, source title (if available), checked date, source type, and confidence.

2. Do not hardcode unverifiable KMÍ claims as truth
- If data is manually entered, mark confidence as `sample` or `needs_verification`.
- Distinguish clearly between official facts, producer interpretation, and AI suggestions.

3. Prefer small, modular changes
- Avoid large rewrites unless requested.
- Keep logic in reusable functions (db, seed loading, analysis, readiness, prompt-building).

4. Naming and encoding
- Use ASCII-only filenames and code identifiers where practical.
- Support Icelandic UTF-8 content in data and UI labels.

5. AI integrations policy
- Do not add OpenAI (or other AI API) integration until schema and data model are stable.
- AI pages may generate prompts but should not make API calls in MVP.

6. Parser/schema safety
- When changing parsers or schema, add/adjust tests or validation scripts.
- Ensure CSV seed validation errors are readable.
