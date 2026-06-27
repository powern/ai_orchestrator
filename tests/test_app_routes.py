from studio.app import app
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project
from studio.services.run_service import create_run_if_not_active


def test_run_project_route_reuses_existing_active_run():
    init_db()
    migrate()

    project_id = create_project("Route Active Project", "Test")
    existing_run_id, _ = create_run_if_not_active(project_id)

    client = app.test_client()
    response = client.post(f"/projects/{project_id}/run")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/runs/{existing_run_id}")

    events = list_events(existing_run_id)
    assert events[-1]["event_type"] == "run_already_active"


def test_project_detail_template_includes_run_form_guard():
    init_db()
    migrate()

    project_id = create_project("Template Run Project", "Test")

    client = app.test_client()
    response = client.get(f"/projects/{project_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'action="/projects/{project_id}/run"' in html
    assert "data-run-form" in html
    assert "Starting..." in html
