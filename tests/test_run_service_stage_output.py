from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.project_service import create_project
from studio.services.run_service import (
    create_run,
    save_stage_output,
    get_stage_output,
)


def test_save_and_get_stage_output():
    init_db()
    migrate()

    project_id = create_project("Stage Output", "Test")
    run_id = create_run(project_id)

    save_stage_output(run_id, "coder_output", "hello")

    assert get_stage_output(run_id, "coder_output") == "hello"
