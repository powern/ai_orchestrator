from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.event_service import list_events
from studio.services.project_service import create_project
from studio.services.run_service import create_run
from studio.services.runtime_service import get_project_runtime


def test_publish_run_event_writes_event_and_runtime():
    init_db()
    migrate()

    project_id = create_project("Publisher Project", "Test")
    run_id = create_run(project_id)

    publish_run_event(
        run_id=run_id,
        project_id=project_id,
        event_type="coder_started",
        stage="coder",
        message="Coder started.",
        payload="payload",
    )

    events = list_events(run_id)
    runtime = get_project_runtime(project_id)

    assert len(events) == 1
    assert events[0]["id"] == runtime["last_event_id"]
    assert events[0]["event_type"] == "coder_started"
    assert events[0]["payload"] == "payload"
    assert runtime["current_stage"] == "coder"
    assert runtime["progress"] == 35


def test_publish_run_event_projects_started_completed_and_failed_runtime():
    init_db()
    migrate()

    project_id = create_project("Publisher Runtime Project", "Test")
    run_id = create_run(project_id)

    planner_event_id = publish_run_event(
        run_id=run_id,
        project_id=project_id,
        event_type="planner_started",
        stage="planner",
        message="Planner started.",
    )

    runtime = get_project_runtime(project_id)
    assert runtime["status"] == "running"
    assert runtime["current_stage"] == "planner"
    assert runtime["last_event_id"] == planner_event_id

    completed_event_id = publish_run_event(
        run_id=run_id,
        project_id=project_id,
        event_type="run_completed",
        stage="tester_completed",
        message="Run completed.",
    )

    runtime = get_project_runtime(project_id)
    assert runtime["status"] == "completed"
    assert runtime["current_stage"] == "tester_completed"
    assert runtime["progress"] == 100
    assert runtime["last_event_id"] == completed_event_id

    failed_run_id = create_run(project_id)
    failed_event_id = publish_run_event(
        run_id=failed_run_id,
        project_id=project_id,
        event_type="run_failed",
        stage="pipeline_failed",
        message="Pipeline failed.",
    )

    runtime = get_project_runtime(project_id)
    assert runtime["status"] == "failed"
    assert runtime["current_stage"] == "pipeline_failed"
    assert runtime["message"] == "Pipeline failed."
    assert runtime["last_event_id"] == failed_event_id
