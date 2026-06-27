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

    assert events[0]["event_type"] == "coder_started"
    assert events[0]["payload"] == "payload"
    assert runtime["current_stage"] == "coder"
    assert runtime["progress"] == 35
