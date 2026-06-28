from studio.app import app
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.project_service import create_project
from studio.services.run_service import create_run, save_stage_output


def test_api_projects_returns_dashboard_metrics():
    init_db()
    migrate()

    create_project("API Project", "Test")

    response = app.test_client().get("/api/projects")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["metrics"]["total_projects"] >= 1
    assert payload["projects"]


def test_api_project_run_events_and_runtime():
    init_db()
    migrate()

    project_id = create_project("API Detail Project", "Test")
    run_id = create_run(project_id)
    save_stage_output(run_id, "runtime_readiness", '{"manual_run_ready": true}')
    publish_run_event(run_id, project_id, "run_completed", "tester_completed", "Done")

    client = app.test_client()

    project_response = client.get(f"/api/projects/{project_id}")
    run_response = client.get(f"/api/runs/{run_id}")
    events_response = client.get(f"/api/events/{run_id}")
    runtime_response = client.get("/api/runtime")

    assert project_response.status_code == 200
    assert project_response.get_json()["runtime"]["status"] == "completed"
    assert run_response.get_json()["run"]["id"] == run_id
    assert run_response.get_json()["project"]["id"] == project_id
    assert run_response.get_json()["runtime"]["status"] == "completed"
    assert run_response.get_json()["events"][0]["event_type"] == "run_completed"
    assert run_response.get_json()["stage_outputs"]["result"] is None
    assert run_response.get_json()["stage_outputs"]["runtime_readiness"]
    assert events_response.get_json()["events"][0]["event_type"] == "run_completed"
    assert runtime_response.get_json()["metrics"]["total_runs"] >= 1
    assert runtime_response.get_json()["projects"]


def test_api_runtime_returns_latest_project_run_state():
    init_db()
    migrate()

    project_id = create_project("Runtime Source Project", "Test")
    run_id = create_run(project_id)
    publish_run_event(run_id, project_id, "coder_started", "coder", "Coder is running")

    response = app.test_client().get("/api/runtime")
    payload = response.get_json()
    project = next(item for item in payload["projects"] if item["id"] == project_id)

    assert response.status_code == 200
    assert project["latest_run_id"] == run_id
    assert project["current_status"] == "running"
    assert project["current_stage"] == "coder"
    assert project["current_agent"] == "coder"
    assert project["current_message"] == "Coder is running"
