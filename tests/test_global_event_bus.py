from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.events.global_bus import global_event_bus
from studio.events.run_events import RunEvent
from studio.services.project_service import create_project
from studio.services.run_service import create_run
from studio.services.runtime_service import get_project_runtime


def test_global_event_bus_updates_runtime_projection():
    init_db()
    migrate()

    project_id = create_project("Global Bus Project", "Test")
    run_id = create_run(project_id)

    global_event_bus.publish(
        RunEvent(
            run_id=run_id,
            project_id=project_id,
            event_type="architect_started",
            stage="architect",
            message="Architect started.",
        )
    )

    runtime = get_project_runtime(project_id)

    assert runtime["current_stage"] == "architect"
    assert runtime["progress"] == 20
