from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.project_service import create_project
from studio.services.runtime_service import (
    calculate_progress,
    get_project_runtime,
    upsert_project_runtime,
)


def test_calculate_progress_completed_is_100():
    assert calculate_progress("tester_completed", "completed") == 100


def test_calculate_progress_by_stage():
    assert calculate_progress("coder", "running") == 35
    assert calculate_progress("executor", "running") == 65


def test_upsert_project_runtime_creates_and_updates_row():
    init_db()
    migrate()

    project_id = create_project("Runtime Project", "Test")

    row = upsert_project_runtime(
        project_id=project_id,
        run_id=10,
        status="running",
        current_stage="coder",
        current_agent="coder",
        message="Coder started",
        last_event_id=100,
    )

    assert row["status"] == "running"
    assert row["progress"] == 35

    row = upsert_project_runtime(
        project_id=project_id,
        run_id=10,
        status="completed",
        current_stage="tester_completed",
        current_agent="tester",
        message="Done",
        last_event_id=101,
    )

    assert row["status"] == "completed"
    assert row["progress"] == 100

    loaded = get_project_runtime(project_id)
    assert loaded["message"] == "Done"
