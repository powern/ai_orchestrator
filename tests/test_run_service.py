from studio.database.db import init_db
from studio.services.project_service import create_project
from studio.services.run_service import (
    create_run,
    get_run,
    get_next_queued_run,
    update_run_status,
)


def test_create_run_for_project():
    init_db()

    project_id = create_project(
        "Run Test Project",
        "Project for run service test",
    )

    run_id = create_run(project_id)
    run = get_run(run_id)

    assert run is not None
    assert run["project_id"] == project_id
    assert run["status"] == "queued"
    assert run["current_stage"] == "queued"


def test_get_next_queued_run_and_update_status():
    init_db()

    project_id = create_project(
        "Queue Test Project",
        "Project for queue test",
    )

    run_id = create_run(project_id)
    next_run = get_next_queued_run()

    assert next_run is not None

    update_run_status(run_id, "running", "planner")

    updated_run = get_run(run_id)

    assert updated_run["status"] == "running"
    assert updated_run["current_stage"] == "planner"
