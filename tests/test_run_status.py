import pytest

from studio.core.status import validate_run_status_transition
from studio.database.db import init_db
from studio.services.project_service import create_project
from studio.services.run_service import create_run, update_run_status


def test_run_status_rejects_terminal_transition():
    init_db()

    project_id = create_project("Terminal Status Project", "Test")
    run_id = create_run(project_id)

    update_run_status(run_id, "completed", "tester_completed")

    with pytest.raises(ValueError):
        update_run_status(run_id, "running", "coder")


def test_validate_run_status_transition_accepts_cancelled():
    validate_run_status_transition("queued", "cancelled")
