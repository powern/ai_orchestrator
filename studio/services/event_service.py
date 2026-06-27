from studio.database.db import get_connection
from studio.events.global_bus import global_event_bus
from studio.events.run_events import RunEvent


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
    project_id = get_project_id_for_run(run_id)

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

    event = RunEvent(
        run_id=run_id,
        project_id=project_id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload=payload,
        event_id=cur.lastrowid,
    )
    global_event_bus.publish(event)

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


def row_to_run_event(row):
    return RunEvent(
        event_id=row["id"],
        run_id=row["run_id"],
        project_id=get_project_id_for_run(row["run_id"]),
        event_type=row["event_type"],
        stage=row["stage"],
        message=row["message"],
        payload=row["payload"],
    )


def replay_events(run_id, handler=None):
    target = handler or global_event_bus.publish
    results = []

    for row in list_events(run_id):
        results.append(target(row_to_run_event(row)))

    return results
