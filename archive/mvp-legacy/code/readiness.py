from __future__ import annotations

import pandas as pd

WEIGHTS = {"required": 0.7, "recommended": 0.2, "strategic": 0.1}


def compute_readiness(requirements: pd.DataFrame, project_docs: pd.DataFrame) -> dict:
    statuses = project_docs.set_index("document_id")["status"].to_dict()

    total_weight = 0.0
    achieved_weight = 0.0
    missing = {"required": [], "recommended": [], "strategic": []}

    for _, row in requirements.iterrows():
        level = row["requirement_level"]
        if level not in WEIGHTS:
            continue
        total_weight += WEIGHTS[level]
        status = statuses.get(row["document_id"], "missing")
        if status in {"done", "complete", "completed"}:
            achieved_weight += WEIGHTS[level]
        else:
            missing[level].append(row["name_is"])

    score = round((achieved_weight / total_weight) * 100, 1) if total_weight else 0.0
    return {"score": score, "missing": missing}


def stage_mismatch_flags(project_stage: str, grant_stage: str) -> list[str]:
    flags = []
    if project_stage and grant_stage and project_stage.lower() not in grant_stage.lower():
        flags.append(
            f"Project stage '{project_stage}' may not match grant best stage '{grant_stage}'."
        )
    return flags
