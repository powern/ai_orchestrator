from studio.config.settings import STAGE_PROGRESS
from studio.database.db import get_connection
from studio.events.handlers import RuntimeHandler
from studio.events.run_events import RunEvent


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


def rebuild_runtime_projection(project_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM project_runtime WHERE project_id = ?",
            (project_id,),
        )
        rows = conn.execute(
            """
            SELECT
                run_events.id AS event_id,
                run_events.run_id AS run_id,
                runs.project_id AS project_id,
                run_events.event_type AS event_type,
                run_events.stage AS stage,
                run_events.message AS message,
                run_events.payload AS payload
            FROM run_events
            JOIN runs ON runs.id = run_events.run_id
            WHERE runs.project_id = ?
            ORDER BY run_events.id ASC
            """,
            (project_id,),
        ).fetchall()
        conn.commit()

    handler = RuntimeHandler()
    runtime = None

    for row in rows:
        runtime = handler(
            RunEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                project_id=row["project_id"],
                event_type=row["event_type"],
                stage=row["stage"],
                message=row["message"],
                payload=row["payload"],
            )
        )

    return runtime or get_project_runtime(project_id)
