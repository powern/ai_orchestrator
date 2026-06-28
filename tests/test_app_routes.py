from studio.app import app
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.event_service import list_events
from studio.services.project_service import create_project
from studio.services.run_service import create_run, create_run_if_not_active, save_stage_output


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


def test_dashboard_template_contains_runtime_polling():
    init_db()
    migrate()

    create_project("Polling Project", "Test")

    client = app.test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "refreshDashboardRuntime" in html
    assert 'fetch("/api/runtime")' in html
    assert "data-project-status" in html
    assert "data-project-progress-bar" in html
    assert "data-project-agent" in html
    assert "data-project-updated" in html


def test_dashboard_uses_latest_runtime_state_instead_of_stale_project_status():
    init_db()
    migrate()

    project_id = create_project("Stale Status Project", "Test")
    run_id = create_run(project_id)
    publish_run_event(run_id, project_id, "planner_started", "planner", "Planner is running")

    client = app.test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'data-project-id="{project_id}"' in html
    assert f'href="/runs/{run_id}">#{run_id}</a>' in html
    assert "status-running" in html
    assert "<td data-project-stage>planner</td>" in html
    assert "<td data-project-agent>planner</td>" in html


def test_run_detail_template_exposes_navigation_and_stage_outputs():
    init_db()
    migrate()

    project_id = create_project("Run Detail Project", "Test")
    previous_run_id = create_run(project_id)
    run_id = create_run(project_id)
    next_run_id = create_run(project_id)

    save_stage_output(run_id, "planner_output", "planner")
    save_stage_output(run_id, "architect_output", "architect")
    save_stage_output(run_id, "coder_raw_output", "raw coder")
    save_stage_output(run_id, "coder_sanitizer_error", "coder error")
    save_stage_output(run_id, "coder_output", "coder")
    save_stage_output(run_id, "executor_output", "executor")
    save_stage_output(run_id, "tester_output", "tester")
    save_stage_output(run_id, "bug_report", "bug")
    save_stage_output(run_id, "failure_analysis", "analysis")
    save_stage_output(run_id, "repair_plan", "plan")
    save_stage_output(run_id, "fix_output", "fix")
    save_stage_output(run_id, "fix_raw_output", "raw fix")
    save_stage_output(run_id, "fix_sanitizer_error", "fix error")
    save_stage_output(run_id, "tester_output_after_fix", "tester after")
    save_stage_output(run_id, "result", "x" * 5000)
    publish_run_event(
        run_id,
        project_id,
        "coder_completed",
        "coder",
        "Coder completed with payload.",
        "large payload body",
    )

    client = app.test_client()
    response = client.get(f"/runs/{run_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f"Run #{run_id}" in html
    assert f'href="/runs/{previous_run_id}"' in html
    assert f'href="/runs/{next_run_id}"' in html
    assert 'href="/"' in html
    assert "Project Name: Run Detail Project" in html
    assert "Current Agent:" in html
    assert "Planner Output" in html
    assert "Architect Output" in html
    assert "Coder Raw Output" in html
    assert "Coder Sanitizer Error" in html
    assert "Executor Output" in html
    assert "Failure Analysis" in html
    assert "Repair Plan" in html
    assert "Fix Raw Output" in html
    assert "Fix Sanitizer Error" in html
    assert "Final Result" in html
    assert "tester after" in html
    assert "<pre>" in html
    assert "View Payload" in html
    assert "large payload body" in html
