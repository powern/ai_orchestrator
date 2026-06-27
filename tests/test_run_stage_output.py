import pytest

from studio.database.db import init_db
from studio.services.project_service import create_project
from studio.services.run_service import create_run, get_run, save_stage_output


def test_save_architect_output():
    init_db()

    project_id = create_project(
        "Stage Output Project",
        "Test saving architect output",
    )

    run_id = create_run(project_id)

    save_stage_output(
        run_id,
        "architect_output",
        "Architecture plan",
    )

    run = get_run(run_id)

    assert run["architect_output"] == "Architecture plan"


def test_save_stage_output_rejects_invalid_field():
    init_db()

    project_id = create_project(
        "Invalid Stage Output Project",
        "Test invalid field",
    )

    run_id = create_run(project_id)

    with pytest.raises(ValueError):
        save_stage_output(run_id, "bad_field", "bad")
