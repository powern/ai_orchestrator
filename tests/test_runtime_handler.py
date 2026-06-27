from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.project_service import create_project
from studio.services.run_service import create_run
from studio.services.runtime_service import get_project_runtime
from studio.events.handlers import RuntimeHandler
from studio.events.run_events import RunEvent


def test_runtime_handler_updates_project_runtime():
    init_db()
    migrate()

    project_id = create_project("Runtime Handler Project", "Test")
    run_id = create_run(project_id)

    handler = RuntimeHandler()

    handler(
        RunEvent(
            run_id=run_id,
            project_id=project_id,
            event_type="coder_started",
            stage="coder",
            message="Coder started.",
        )
    )

    runtime = get_project_runtime(project_id)

    assert runtime["status"] == "running"
    assert runtime["current_stage"] == "coder"
    assert runtime["progress"] == 35
    assert runtime["message"] == "Coder started."


def test_runtime_handler_marks_completed():
    init_db()
    migrate()

    project_id = create_project("Runtime Completed Project", "Test")
    run_id = create_run(project_id)

    RuntimeHandler()(
        RunEvent(
            run_id=run_id,
            project_id=project_id,
            event_type="run_completed",
            stage="tester_completed",
            message="Run completed.",
        )
    )

    runtime = get_project_runtime(project_id)

    assert runtime["status"] == "completed"
    assert runtime["progress"] == 100
