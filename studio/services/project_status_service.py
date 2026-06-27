from studio.database.db import get_connection


def calculate_project_status(project_id):
    with get_connection() as conn:
        run = conn.execute(
            """
            SELECT status, current_stage
            FROM runs
            WHERE project_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()

    if run is None:
        return "new"

    if run["status"] == "completed":
        return "completed"

    if run["status"] == "failed":
        return "failed"

    if run["status"] == "running":
        return "running"

    if run["status"] == "queued":
        return "queued"

    return "unknown"


def update_project_status(project_id):
    status = calculate_project_status(project_id)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE projects
            SET status = ?
            WHERE id = ?
            """,
            (status, project_id),
        )
        conn.commit()

    return status
