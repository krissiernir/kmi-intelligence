from __future__ import annotations


def build_prompt(mode: str, project: dict, grant: dict, docs: dict, criteria: list[str], allocation_note: str) -> str:
    return f"""
Mode: {mode}

You are assisting an Icelandic film producer with KMÍ/Kvikmyndasjóður application preparation.

Project profile:
- Title: {project.get('title')}
- Format: {project.get('format')}
- Stage: {project.get('stage')}
- Writer: {project.get('writer')}
- Director: {project.get('director')}
- Producer: {project.get('producer')}
- Logline: {project.get('logline')}

Grant summary:
- Name: {grant.get('name_is')}
- Category: {grant.get('category')}
- Purpose: {grant.get('purpose')}
- Best stage: {grant.get('best_stage')}
- Eligibility: {grant.get('eligibility_summary')}

Documents:
- Required: {', '.join(docs.get('required', [])) or 'None'}
- Recommended: {', '.join(docs.get('recommended', [])) or 'None'}
- Strategic: {', '.join(docs.get('strategic', [])) or 'None'}

Missing documents:
- Required: {', '.join(docs.get('missing_required', [])) or 'None'}
- Recommended: {', '.join(docs.get('missing_recommended', [])) or 'None'}
- Strategic: {', '.join(docs.get('missing_strategic', [])) or 'None'}

Linked criteria:
- {chr(10).join(criteria) if criteria else 'No criteria linked in sample data.'}

Allocation context (sample data):
{allocation_note}

Instructions:
1) Analyze both artistic strength and production feasibility.
2) Be skeptical and identify weak claims or missing proof.
3) Distinguish official-source facts, producer interpretation, and AI suggestions.
4) Avoid presenting any unverifiable claim as official KMÍ policy.
""".strip()
