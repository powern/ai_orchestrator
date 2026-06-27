from studio.database.db import get_connection


def migrate():
    with get_connection() as conn:

        conn.execute("""
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            run_id INTEGER NOT NULL,

            event_time DATETIME DEFAULT CURRENT_TIMESTAMP,

            event_type TEXT NOT NULL,

            stage TEXT,

            message TEXT,

            payload TEXT,

            FOREIGN KEY(run_id)
                REFERENCES runs(id)
        )
        """)


        columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        ]

        if "bug_report" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN bug_report TEXT")


        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_runtime (
                project_id INTEGER PRIMARY KEY,
                run_id INTEGER,
                status TEXT NOT NULL DEFAULT 'new',
                current_stage TEXT,
                current_agent TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                last_event_id INTEGER,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)

        conn.commit()
