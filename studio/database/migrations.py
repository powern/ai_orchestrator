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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_handoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                producer TEXT NOT NULL,
                consumer TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)

        columns = [row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()]

        if "bug_report" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN bug_report TEXT")

        if "coder_raw_output" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN coder_raw_output TEXT")

        if "coder_sanitizer_error" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN coder_sanitizer_error TEXT")

        if "executor_output" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN executor_output TEXT")

        if "failure_analysis" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN failure_analysis TEXT")

        if "repair_plan" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN repair_plan TEXT")

        if "fix_raw_output" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN fix_raw_output TEXT")

        if "fix_output" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN fix_output TEXT")

        if "fix_sanitizer_error" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN fix_sanitizer_error TEXT")

        if "tester_output_before_fix" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN tester_output_before_fix TEXT")

        if "tester_output_after_fix" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN tester_output_after_fix TEXT")

        if "runtime_readiness" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN runtime_readiness TEXT")

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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS engineering_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                run_id INTEGER,
                status TEXT NOT NULL DEFAULT 'observed',
                confidence REAL,
                proposed_objective TEXT,
                should_continue INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS engineering_cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                cycle_number INTEGER NOT NULL,
                objective TEXT,
                status TEXT NOT NULL DEFAULT 'proposed',
                confidence_before REAL,
                confidence_after REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES engineering_sessions(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                run_id INTEGER,
                payload_json TEXT NOT NULL,
                confidence_json TEXT,
                decision_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES engineering_sessions(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                cycle_id INTEGER,
                run_id INTEGER,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES engineering_sessions(id),
                FOREIGN KEY(cycle_id) REFERENCES engineering_cycles(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)

        conn.commit()
