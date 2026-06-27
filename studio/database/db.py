import os
import sqlite3

from studio.config.settings import DATABASE_PATH


def get_database_path():
    return os.environ.get("AI_STUDIO_DB_PATH", str(DATABASE_PATH))


def get_connection():
    conn = sqlite3.connect(get_database_path())
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
                coder_output TEXT,
                tester_output TEXT,
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
