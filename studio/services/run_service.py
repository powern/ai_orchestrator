from studio.database.db import get_connection


def create_run(project_id):
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (project_id, status, current_stage)
            VALUES (?, 'queued', 'queued')
            """,
            (project_id,),
        )
        conn.commit()
        return cur.lastrowid


def list_runs_for_project(project_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM runs
            WHERE project_id = ?
            ORDER BY id DESC
            """,
            (project_id,),
        ).fetchall()


def get_run(run_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()


def get_next_queued_run():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM runs
            WHERE status = 'queued'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()


def update_run_status(run_id, status, current_stage=None, result=None):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status = ?,
                current_stage = COALESCE(?, current_stage),
                result = COALESCE(?, result),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, current_stage, result, run_id),
        )
        conn.commit()


def save_stage_output(run_id, field_name, output):
    allowed_fields = {
        "planner_output",
        "architect_output",
        "coder_output",
        "tester_output",
        "bug_report",
        "result",
    }

    if field_name not in allowed_fields:
        raise ValueError(f"Unsupported output field: {field_name}")

    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE runs
            SET {field_name} = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (output, run_id),
        )
        conn.commit()


def get_stage_output(run_id, field_name):
    allowed_fields = {
        "planner_output",
        "architect_output",
        "coder_output",
        "tester_output",
        "bug_report",
        "result",
    }

    if field_name not in allowed_fields:
        raise ValueError(f"Unsupported output field: {field_name}")

    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {field_name} FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    return row[field_name]
