from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("db/kmi.db")


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            fetched_at TEXT,
            checked_at TEXT,
            content_hash TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS grants (
            id INTEGER PRIMARY KEY,
            name_is TEXT NOT NULL,
            name_en TEXT,
            category TEXT NOT NULL,
            project_types TEXT,
            best_stage TEXT,
            purpose TEXT,
            eligibility_summary TEXT,
            max_amount_isk INTEGER,
            deadline_type TEXT,
            source_id INTEGER,
            last_checked TEXT,
            confidence TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            name_is TEXT NOT NULL,
            name_en TEXT,
            document_type TEXT,
            purpose TEXT,
            what_it_must_prove TEXT,
            common_weaknesses TEXT,
            template_path TEXT,
            prompt_path TEXT
        );

        CREATE TABLE IF NOT EXISTS grant_document_requirements (
            id INTEGER PRIMARY KEY,
            grant_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            requirement_level TEXT NOT NULL,
            notes TEXT,
            source_id INTEGER,
            confidence TEXT,
            FOREIGN KEY (grant_id) REFERENCES grants(id),
            FOREIGN KEY (document_id) REFERENCES documents(id),
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS criteria (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            axis TEXT,
            description TEXT,
            evidence_examples TEXT,
            red_flags TEXT
        );

        CREATE TABLE IF NOT EXISTS grant_criteria (
            id INTEGER PRIMARY KEY,
            grant_id INTEGER NOT NULL,
            criterion_id INTEGER NOT NULL,
            importance TEXT,
            notes TEXT,
            FOREIGN KEY (grant_id) REFERENCES grants(id),
            FOREIGN KEY (criterion_id) REFERENCES criteria(id)
        );

        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY,
            project_title TEXT NOT NULL,
            year INTEGER,
            date TEXT,
            grant_id INTEGER,
            grant_category_raw TEXT,
            grant_name_raw TEXT,
            amount_isk INTEGER,
            company_name TEXT,
            producer_name TEXT,
            director_name TEXT,
            writer_name TEXT,
            format TEXT,
            stage TEXT,
            source_id INTEGER,
            notes TEXT,
            FOREIGN KEY (grant_id) REFERENCES grants(id),
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            roles TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            format TEXT,
            stage TEXT,
            writer TEXT,
            director TEXT,
            producer TEXT,
            company TEXT,
            logline TEXT,
            synopsis_short TEXT,
            rights_status TEXT,
            target_grant_id INTEGER,
            notes TEXT,
            FOREIGN KEY (target_grant_id) REFERENCES grants(id)
        );

        CREATE TABLE IF NOT EXISTS project_documents (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            status TEXT,
            file_path TEXT,
            notes TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            grant_id INTEGER NOT NULL,
            deadline TEXT,
            status TEXT,
            submitted_at TEXT,
            result TEXT,
            amount_awarded_isk INTEGER,
            feedback TEXT,
            notes TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (grant_id) REFERENCES grants(id)
        );
        """
    )
    conn.commit()
