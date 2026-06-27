from studio.database.db import get_connection


STAGE_PROGRESS = {
    "queued": 0,
    "planner": 10,
    "architect": 20,
    "coder": 35,
    "static_reviewer": 50,
    "executor": 65,
    "tester": 80,
    "reviewer": 90,
    "tester_completed": 100,
    "static_review_failed": 50,
    "tester_failed": 80,
    "pipeline_failed": 100,
}


def calculate_progress(stage, status):
    if status == "completed":
        return 100

    if status == "failed":
        return STAGE_PROGRESS.get(stage, 100)

    return STAGE_PROGRESS.get(stage, 0)


def upsert_project_runtime(
    project_id,
    run_id=None,
    status="new",
    current_stage=None,
    current_agent=None,
    message=None,
    last_event_id=None,
):
    progress = calculate_progress(current_stage, status)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project_runtime (
                project_id,
                run_id,
                status,
                current_stage,
                current_agent,
                progress,
                message,
                last_event_id,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id) DO UPDATE SET
                run_id = excluded.run_id,
                status = excluded.status,
                current_stage = excluded.current_stage,
                current_agent = excluded.current_agent,
                progress = excluded.progress,
                message = excluded.message,
                last_event_id = excluded.last_event_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                project_id,
                run_id,
                status,
                current_stage,
                current_agent,
                progress,
                message,
                last_event_id,
            ),
        )
        conn.commit()

    return get_project_runtime(project_id)


def get_project_runtime(project_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM project_runtime
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
