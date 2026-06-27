from studio.database.db import get_connection, init_db
from studio.database.migrations import migrate
from studio.services.project_service import create_project
from studio.services.project_status_service import (
    calculate_project_status,
    update_project_status,
)
from studio.services.run_service import create_run, update_run_status


def test_project_status_is_new_without_runs():
    init_db()
    migrate()

    project_id = create_project("Status New", "No runs yet")

    assert calculate_project_status(project_id) == "new"


def test_project_status_follows_latest_run():
    init_db()
    migrate()

    project_id = create_project("Status Latest Run", "Test")
    run_id = create_run(project_id)

    update_run_status(run_id, "running", "coder")

    assert calculate_project_status(project_id) == "running"

    update_run_status(run_id, "completed", "tester_completed")

    assert calculate_project_status(project_id) == "completed"


def test_update_project_status_writes_to_project():
    init_db()
    migrate()

    project_id = create_project("Status Write", "Test")
    run_id = create_run(project_id)

    update_run_status(run_id, "failed", "tester_failed")

    status = update_project_status(project_id)

    with get_connection() as conn:
        project = conn.execute(
            "SELECT status FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    assert status == "failed"
    assert project["status"] == "failed"
