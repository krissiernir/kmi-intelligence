from __future__ import annotations

from pathlib import Path
import sqlite3
import pandas as pd

from .db import create_schema, get_connection, DB_PATH

SEED_DIR = Path("data/seed")

TABLE_SPECS = {
    "sources": ["id", "title", "url", "source_type", "fetched_at", "checked_at", "content_hash", "notes"],
    "grants": ["id", "name_is", "name_en", "category", "project_types", "best_stage", "purpose", "eligibility_summary", "max_amount_isk", "deadline_type", "source_id", "last_checked", "confidence"],
    "documents": ["id", "name_is", "name_en", "document_type", "purpose", "what_it_must_prove", "common_weaknesses", "template_path", "prompt_path"],
    "grant_document_requirements": ["id", "grant_id", "document_id", "requirement_level", "notes", "source_id", "confidence"],
    "criteria": ["id", "name", "axis", "description", "evidence_examples", "red_flags"],
    "grant_criteria": ["id", "grant_id", "criterion_id", "importance", "notes"],
    "allocations": ["id", "project_title", "year", "date", "grant_id", "grant_category_raw", "grant_name_raw", "amount_isk", "company_name", "producer_name", "director_name", "writer_name", "format", "stage", "source_id", "notes"],
    "projects": ["id", "title", "format", "stage", "writer", "director", "producer", "company", "logline", "synopsis_short", "rights_status", "target_grant_id", "notes"],
    "project_documents": ["id", "project_id", "document_id", "status", "file_path", "notes"],
}


def validate_seed_file(table: str, df: pd.DataFrame) -> None:
    missing = [col for col in TABLE_SPECS[table] if col not in df.columns]
    if missing:
        raise ValueError(f"{table}.csv is missing required columns: {missing}")


def reset_seed_tables(conn: sqlite3.Connection) -> None:
    for table in reversed(list(TABLE_SPECS.keys()) + ["applications", "people", "companies"]):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def load_seed_data(conn: sqlite3.Connection, seed_dir: Path = SEED_DIR) -> None:
    create_schema(conn)
    reset_seed_tables(conn)

    for table in TABLE_SPECS:
        csv_path = seed_dir / f"{table}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing seed file: {csv_path}")
        df = pd.read_csv(csv_path)
        validate_seed_file(table, df)
        df[TABLE_SPECS[table]].to_sql(table, conn, if_exists="append", index=False)

    conn.commit()


def main() -> None:
    conn = get_connection(DB_PATH)
    load_seed_data(conn)
    print("Seed load completed.")


if __name__ == "__main__":
    main()
