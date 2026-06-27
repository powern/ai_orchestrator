from studio.database.db import init_db
from studio.services.project_service import create_project
from studio.services.run_service import (
    create_run,
    create_run_if_not_active,
    get_active_run_for_project,
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


def test_create_run_if_not_active_creates_first_run():
    init_db()

    project_id = create_project("First Active Run Project", "Test")

    run_id, created = create_run_if_not_active(project_id)

    assert created is True
    assert get_run(run_id)["status"] == "queued"


def test_create_run_if_not_active_reuses_queued_run():
    init_db()

    project_id = create_project("Queued Active Run Project", "Test")
    first_run_id, created = create_run_if_not_active(project_id)

    second_run_id, second_created = create_run_if_not_active(project_id)

    assert created is True
    assert second_created is False
    assert second_run_id == first_run_id
    assert get_active_run_for_project(project_id)["id"] == first_run_id


def test_create_run_if_not_active_reuses_running_run():
    init_db()

    project_id = create_project("Running Active Run Project", "Test")
    first_run_id, _ = create_run_if_not_active(project_id)
    update_run_status(first_run_id, "running", "coder")

    second_run_id, created = create_run_if_not_active(project_id)

    assert created is False
    assert second_run_id == first_run_id


def test_create_run_if_not_active_allows_new_run_after_completed():
    init_db()

    project_id = create_project("Completed Run Project", "Test")
    first_run_id, _ = create_run_if_not_active(project_id)
    update_run_status(first_run_id, "completed", "tester_completed")

    second_run_id, created = create_run_if_not_active(project_id)

    assert created is True
    assert second_run_id != first_run_id


def test_create_run_if_not_active_allows_new_run_after_failed():
    init_db()

    project_id = create_project("Failed Run Project", "Test")
    first_run_id, _ = create_run_if_not_active(project_id)
    update_run_status(first_run_id, "failed", "tester_failed")

    second_run_id, created = create_run_if_not_active(project_id)

    assert created is True
    assert second_run_id != first_run_id


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
