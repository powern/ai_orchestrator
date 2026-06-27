from studio.database.db import get_connection


def get_project_id_for_run(run_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    return row["project_id"]


def add_event(run_id, event_type, stage=None, message="", payload=""):
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO run_events
            (
                run_id,
                event_type,
                stage,
                message,
                payload
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                event_type,
                stage,
                message,
                payload,
            ),
        )
        conn.commit()

    try:
        from studio.events.run_events import RunEvent
        from studio.events.handlers import RuntimeHandler

        RuntimeHandler()(
            RunEvent(
                run_id=run_id,
                project_id=get_project_id_for_run(run_id),
                event_type=event_type,
                stage=stage,
                message=message,
                payload=payload,
            )
        )
    except Exception:
        pass

    return cur.lastrowid


def list_events(run_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM run_events
            WHERE run_id=?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
