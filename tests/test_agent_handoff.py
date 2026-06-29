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


def test_run_detail_renders_legacy_handoff_without_decision_record():
    setup_database()
    from studio.app import app

    project_id = create_project("Legacy Handoff UI", "Create a small app.")
    run_id = create_run(project_id)
    legacy_payload = {
        "producer": "architect",
        "consumer": "coder",
        "summary": "Legacy architecture summary.",
        "implementation_contract": {"entrypoint": "app/main.py"},
        "recommended_focus": ["tests"],
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_handoffs
            (
                run_id,
                stage,
                producer,
                consumer,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, "architect", "architect", "coder", __import__("json").dumps(legacy_payload)),
        )
        conn.commit()

    response = app.test_client().get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert b"Legacy handoff format" in response.data
    assert b"Legacy architecture summary" in response.data


def test_run_detail_renders_new_decision_record_handoff():
    setup_database()
    from studio.app import app

    project_id = create_project("Decision Handoff UI", "Create a small app.")
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "architect")
    append_handoff(
        run_id,
        "architect",
        build_handoff(
            "architect",
            "coder",
            "Use app package root.",
            context,
            implementation_contract={"entrypoint": "app/main.py"},
        ),
    )

    response = app.test_client().get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert b"Protected Decisions" in response.data
    assert b"Confidence:" in response.data


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
    assert "output: canonical_executor_actions" in payload["decision_record"]["decisions"]
    assert "generated_files: ['app/main.py']" in payload["decision_record"]["decisions"]
    assert "original_user_request" in payload["decision_record"]["protected_decisions"]
    assert payload["implementation_contract"]["generated_files"] == ["app/main.py"]
    assert payload["implementation_contract"]["run_command"] == "python app/main.py"


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


def test_architect_decision_record_uses_project_graph_fields(tmp_path):
    setup_database()
    project_id = create_project("Architect Concrete", "Create a Flask app.")
    run_id = create_run(project_id)
    workspace = tmp_path
    (workspace / "app").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "app" / "__init__.py").write_text("")
    (workspace / "app" / "main.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'ok'\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n",
        encoding="utf-8",
    )
    (workspace / "tests" / "test_main.py").write_text("def test_ok():\n    assert True\n")
    context = build_agent_context(run_id, "architect", workspace_path=str(workspace))

    handoff = build_handoff(
        "architect",
        "coder",
        "Architect selected Flask package structure.",
        context,
        implementation_contract={"dependency_strategy": "requirements.txt"},
    )
    payload = handoff.to_dict()

    assert payload["decision_record"]["assumptions"]["package_root"] == "app"
    assert payload["implementation_contract"]["framework"] == "flask"
    assert payload["implementation_contract"]["entrypoint"] == "app/main.py"
    assert payload["implementation_contract"]["route_contract"] == ["/"]
    assert payload["implementation_contract"]["test_import_contract"] == "from app.main import app"


def test_repair_and_fix_decision_records_include_targets_and_preservation():
    setup_database()
    project_id = create_project("Repair Concrete", "Create a calculator.")
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "repair_planner")

    repair = build_handoff(
        "repair_planner",
        "fix",
        "Repair Planner selected concrete repair targets.",
        context,
        implementation_contract={
            "repair_targets": ["app/main.py"],
            "secondary_targets": ["tests/test_main.py"],
            "test_modification_policy": "Modify tests only when tests are wrong.",
        },
    ).to_dict()
    fix = build_handoff(
        "fix",
        "static_reviewer",
        '[{"action":"write_file","path":"app/main.py","content":"def main():\\n    return 1\\n"}]',
        context,
        implementation_contract={"original_requirements_preserved": True},
    ).to_dict()

    assert "repair_targets: ['app/main.py']" in repair["decision_record"]["decisions"]
    assert "test_modification_policy" in "\n".join(repair["decision_record"]["decisions"])
    assert fix["implementation_contract"]["changed_files"] == ["app/main.py"]
    assert "original_requirements_preserved: True" in fix["decision_record"]["decisions"]


def test_handoff_table_exists_after_migration():
    setup_database()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agent_handoffs'"
        ).fetchone()

    assert row is not None
