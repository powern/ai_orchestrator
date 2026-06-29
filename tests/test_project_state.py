import json
from pathlib import Path

from studio.core.failure_analysis import FailureAnalyzer
from studio.core.project_state import ProjectStateBuilder
from studio.core.tester_result import StageTestResult
from studio.reviewer.static_agent import StaticReviewerAgent


def write_file(root: Path, relative_path: str, content: str = "") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def flask_bad_actions():
    return [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": (
                "from flask import Flask\n\n"
                "@app.route('/')\n"
                "def index():\n"
                "    return 'ok'\n"
            ),
        },
        {
            "action": "write_file",
            "path": "tests/test_app.py",
            "content": "def test_placeholder():\n    assert True\n",
        },
        {"action": "write_file", "path": "requirements.txt", "content": "Flask==3.0.0\n"},
    ]


def test_project_state_builds_from_actual_files(tmp_path):
    write_file(tmp_path, "app/main.py", "def main():\n    return 'ok'\n")

    state = ProjectStateBuilder().build(workspace_path=tmp_path)

    assert state.actual_files["count"] == 1
    assert state.planned_files["count"] == 0
    assert state.merged_files["count"] == 1
    assert state.state_source["graph_source"] == "merged_files"


def test_project_state_builds_from_planned_executor_actions():
    state = ProjectStateBuilder().build(executor_actions=flask_bad_actions())

    planned = state.planned_files["files"]

    assert state.actual_files["count"] == 0
    assert state.planned_files["count"] == 3
    assert any(item["path"] == "app/main.py" for item in planned)
    assert state.state_source["has_planned_actions"] is True


def test_project_state_merges_actual_and_planned_files(tmp_path):
    write_file(tmp_path, "app/main.py", "def main():\n    return 'actual'\n")
    actions = [
        {"action": "write_file", "path": "app/main.py", "content": "planned\n"},
        {"action": "write_file", "path": "tests/test_main.py", "content": "def test_ok(): pass\n"},
    ]

    state = ProjectStateBuilder().build(workspace_path=tmp_path, executor_actions=actions)
    merged = {item["path"]: item for item in state.merged_files["files"]}

    assert state.actual_files["count"] == 1
    assert state.planned_files["count"] == 2
    assert state.merged_files["count"] == 2
    assert merged["app/main.py"]["source"] == "actual"
    assert merged["tests/test_main.py"]["source"] == "planned"


def test_project_state_tracks_planned_file_source():
    state = ProjectStateBuilder().build(executor_actions=flask_bad_actions())
    planned_main = next(
        item for item in state.planned_files["files"] if item["path"] == "app/main.py"
    )

    assert planned_main["source"] == "planned"
    assert planned_main["exists_on_disk"] is False
    assert "@app.route" in planned_main["content_preview"]


def test_project_graph_analyzes_planned_files_before_execution():
    state = ProjectStateBuilder().build(executor_actions=flask_bad_actions())

    assert state.project_graph["summary"]["project_types"] == ["flask", "python"]
    assert state.project_graph["summary"]["route_count"] == 1
    assert state.project_graph["routes"][0]["path"] == "/"


def test_execution_contract_infers_from_planned_files():
    state = ProjectStateBuilder().build(executor_actions=flask_bad_actions())

    assert state.execution_contract["language"] == "python"
    assert state.execution_contract["source_roots"] == ["app"]
    assert state.execution_contract["test"]["command"] == "pytest -q"


def test_static_review_uses_project_state_for_planned_flask_actions():
    state = ProjectStateBuilder().build(executor_actions=flask_bad_actions())

    result = StaticReviewerAgent().review(flask_bad_actions(), project_state=state)

    assert result.approved is False
    assert any(
        "Flask route exists but app object is not defined" in item
        for item in result.findings
    )
    assert state.project_graph["summary"]["route_count"] == 1


def test_failure_analyzer_receives_project_state_for_static_review_failure():
    state = ProjectStateBuilder().build(executor_actions=flask_bad_actions())
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="Static review rejected executor actions.",
        stderr="Flask route exists but app object is not defined in app/main.py",
    )

    analysis = FailureAnalyzer().analyze(
        Path("missing-workspace"),
        tester_result,
        project_state=state.to_dict(),
    )

    assert "app/main.py" in analysis.evidence_pack["relevant_files"]
    assert analysis.evidence_pack["project_graph"]["summary"]["route_count"] == 1
    assert analysis.evidence_pack["execution_contract"]["language"] == "python"


def test_agent_context_includes_project_state_summary(tmp_path):
    from studio.contracts import build_agent_context
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run

    init_db()
    migrate()
    project_id = create_project("State Context", "Create app.")
    run_id = create_run(project_id)
    write_file(tmp_path, "app/main.py", "def main():\n    return 'ok'\n")

    context = build_agent_context(run_id, "coder", workspace_path=str(tmp_path))
    payload = context.to_dict()

    assert payload["project"]["project_state"]["merged_files"]["count"] == 1
    assert payload["project"]["project_state_summary"]["actual_file_count"] == 1


def test_run_api_exposes_project_state_summary():
    from studio.app import app
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run, save_stage_output

    init_db()
    migrate()
    project_id = create_project("State API", "Create app.")
    run_id = create_run(project_id)
    save_stage_output(run_id, "coder_output", json.dumps(flask_bad_actions()))

    response = app.test_client().get(f"/api/runs/{run_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["project_state_summary"]["planned_file_count"] == 3
    assert payload["project_state_summary"]["routes"] == ["/"]
