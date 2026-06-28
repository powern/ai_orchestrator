import os
import sqlite3
from pathlib import Path

from studio.config.settings import DATABASE_PATH


def get_database_path():
    configured_path = os.environ.get("AI_STUDIO_DB_PATH")

    if (
        configured_path
        and os.name == "nt"
        and (configured_path.startswith("/tmp/") or configured_path.startswith("\\tmp\\"))
    ):
        return str(DATABASE_PATH.parent / ".tmp" / Path(configured_path).name)

    return configured_path or str(DATABASE_PATH)


def get_connection():
    database_path = Path(get_database_path())
    database_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                workspace_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                current_stage TEXT NOT NULL DEFAULT 'queued',
                planner_output TEXT,
                architect_output TEXT,
                coder_raw_output TEXT,
                coder_output TEXT,
                coder_sanitizer_error TEXT,
                fix_raw_output TEXT,
                fix_output TEXT,
                fix_sanitizer_error TEXT,
                tester_output TEXT,
                tester_output_before_fix TEXT,
                tester_output_after_fix TEXT,
                bug_report TEXT,
                result TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                event_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                stage TEXT,
                message TEXT,
                payload TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)

        conn.commit()
