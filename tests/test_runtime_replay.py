from studio.database.db import get_connection, init_db
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.project_service import create_project
from studio.services.run_service import create_run
from studio.services.runtime_service import (
    get_project_runtime,
    rebuild_runtime_projection,
    upsert_project_runtime,
)


def test_rebuild_runtime_projection_replays_project_events():
    init_db()
    migrate()

    project_id = create_project("Replay Runtime Project", "Test")
    run_id = create_run(project_id)

    publish_run_event(
        run_id=run_id,
        project_id=project_id,
        event_type="planner_started",
        stage="planner",
        message="Planner started.",
    )
    final_event_id = publish_run_event(
        run_id=run_id,
        project_id=project_id,
        event_type="run_completed",
        stage="tester_completed",
        message="Run completed.",
    )

    upsert_project_runtime(
        project_id=project_id,
        run_id=run_id,
        status="failed",
        current_stage="pipeline_failed",
        current_agent="pipeline_failed",
        message="stale",
        last_event_id=-1,
    )

    runtime = rebuild_runtime_projection(project_id)

    assert runtime["status"] == "completed"
    assert runtime["current_stage"] == "tester_completed"
    assert runtime["progress"] == 100
    assert runtime["last_event_id"] == final_event_id

    loaded = get_project_runtime(project_id)
    assert loaded["message"] == "Run completed."
