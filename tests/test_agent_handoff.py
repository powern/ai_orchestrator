from pathlib import Path

from studio.contracts import append_handoff, build_agent_context, build_handoff
from studio.contracts.handoff import load_handoff_history, load_latest_handoff
from studio.database.db import get_connection, init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run


def setup_database():
    init_db()
    migrate()


def test_handoff_persists_to_database_workspace_and_events():
    setup_database()
    project_id = create_project("Handoff", "Create a small app.")
    project = dict(get_project(project_id))
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "planner")
    handoff = build_handoff(
        producer="planner",
        consumer="architect",
        summary="Build app/main.py and tests/test_main.py.",
        agent_context=context,
    )

    handoff_id = append_handoff(
        run_id,
        "planner",
        handoff,
        workspace_path=project["workspace_path"],
    )
    latest = load_latest_handoff(run_id)
    history = load_handoff_history(run_id)
    artifact = (
        Path(project["workspace_path"])
        / ".orchestrator"
        / "handoff"
        / f"{handoff_id:04d}-planner.json"
    )
    event_types = [event["event_type"] for event in list_events(run_id)]

    assert latest["payload"]["producer"] == "planner"
    assert latest["payload"]["decision_record"]["agent"] == "planner"
    assert latest["payload"]["decision_record"]["expected_next_agent"] == "architect"
    assert history[0]["payload"]["consumer"] == "architect"
    assert artifact.exists()
    assert "agent_handoff_recorded" in event_types


def test_agent_context_contains_handoff_memory():
    setup_database()
    project_id = create_project("Handoff Memory", "Create a calculator.")
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "planner")
    append_handoff(
        run_id,
        "planner",
        build_handoff("planner", "architect", "Use app as package root.", context),
    )

    next_context = build_agent_context(run_id, "architect")
    payload = next_context.to_dict()

    assert payload["pipeline"]["latest_handoff"]["producer"] == "planner"
    assert payload["pipeline"]["handoff_history"][0]["consumer"] == "architect"


def test_run_detail_and_api_expose_engineering_timeline():
    setup_database()
    from studio.app import app

    project_id = create_project("Handoff UI", "Create a small app.")
    project = dict(get_project(project_id))
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "planner")
    append_handoff(
        run_id,
        "planner",
        build_handoff("planner", "architect", "Plan app and tests.", context),
        workspace_path=project["workspace_path"],
    )

    page = app.test_client().get(f"/runs/{run_id}")
    api = app.test_client().get(f"/api/runs/{run_id}").get_json()

    assert page.status_code == 200
    assert b"Engineering Timeline" in page.data
    assert api["agent_handoffs"][0]["producer"] == "planner"


def test_handoff_summarizes_executor_json_as_decision_record():
    setup_database()
    project_id = create_project("Decision Handoff", "Create a small app.")
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "coder")
    raw_executor_json = (
        '[{"action":"write_file","path":"app/main.py",'
        '"content":"def main():\\n    return \\"secret code\\"\\n"}]'
    )

    handoff = build_handoff(
        "coder",
        "executor",
        raw_executor_json,
        context,
        implementation_contract={"output": "canonical_executor_actions"},
    )
    payload = handoff.to_dict()

    assert "secret code" not in payload["summary"]
    assert "Produced canonical Executor action plan" in payload["summary"]
    assert payload["decision_record"]["decisions"] == ["output: canonical_executor_actions"]
    assert "original_user_request" in payload["decision_record"]["protected_decisions"]


def test_handoff_filters_code_like_summary_lines():
    setup_database()
    project_id = create_project("Decision Filter", "Create a small app.")
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "architect")

    handoff = build_handoff(
        "architect",
        "coder",
        "Use app as package root.\ndef main():\n    return 'implementation'\n",
        context,
    )

    assert "def main" not in handoff.summary
    assert "Use app as package root." in handoff.summary


def test_handoff_table_exists_after_migration():
    setup_database()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agent_handoffs'"
        ).fetchone()

    assert row is not None
