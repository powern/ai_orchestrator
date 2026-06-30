import json

from studio.contracts.execution import infer_execution_contract
from studio.contracts.project_specification import build_project_specification
from studio.core.failure_analysis import FailureAnalyzer
from studio.core.project_state import ProjectStateBuilder
from studio.core.tester_result import StageTestResult


def test_project_specification_extracts_explicit_flask_request():
    spec = build_project_specification("Create a Flask application for notes.").to_dict()

    assert spec["project_type"] == "web_app"
    assert spec["language"] == "python"
    assert spec["framework"] == "flask"
    assert spec["runtime"]["kind"] == "web"
    assert "flask" in spec["dependencies"]
    assert spec["confidence"] >= 0.7


def test_crud_notes_request_extracts_note_entity_and_features():
    spec = build_project_specification(
        "Build a notes CRUD app to create, edit, delete, view and list notes with created date."
    ).to_dict()

    feature_kinds = {feature["kind"] for feature in spec["features"]}

    assert {"crud_create", "crud_update", "crud_delete", "crud_read", "crud_list"} <= feature_kinds
    assert spec["entities"] == [{"name": "note", "fields": ["title", "text", "created_date"]}]


def test_project_specification_seeds_execution_contract():
    spec = build_project_specification("Create a Flask application.").to_dict()

    contract = infer_execution_contract(project_specification=spec).to_dict()

    assert contract["language"] == "python"
    assert contract["source_roots"] == ["app"]
    assert contract["test_roots"] == ["tests"]
    assert contract["run"]["command"] == "python app/main.py"
    assert contract["run"]["host"] == "0.0.0.0"
    assert contract["run"]["port"] == 5000
    assert contract["test"]["command"] == "pytest -q"
    assert contract["module_strategy"]["import_root"] == "app"


def test_project_state_includes_specification_when_workspace_empty(tmp_path):
    state = ProjectStateBuilder().build(
        workspace_path=tmp_path,
        request_text="Create a Flask application.",
    )

    assert state.project_specification["language"] == "python"
    assert state.project_specification["framework"] == "flask"
    assert state.execution_contract["language"] == "python"
    assert state.summary()["specification_confidence"] >= 0.7


def test_agent_context_includes_project_specification():
    from studio.contracts import build_agent_context
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run

    init_db()
    migrate()
    project_id = create_project("Spec Context", "Create a Flask application.")
    run_id = create_run(project_id)

    context = build_agent_context(run_id, "coder")
    payload = context.to_dict()

    assert payload["task"]["project_specification"]["framework"] == "flask"
    assert payload["project"]["project_specification"]["language"] == "python"
    assert payload["project"]["execution_contract"]["run"]["command"] == "python app/main.py"


def test_handoff_decision_record_includes_project_specification():
    from studio.contracts.handoff import build_handoff

    spec = build_project_specification("Create a Flask application.").to_dict()
    context = {
        "task": {},
        "project": {"project_specification": spec, "project_graph": {}},
        "pipeline": {},
        "evidence": {},
    }

    payload = build_handoff("architect", "coder", "Use Flask.", context).to_dict()
    decisions = "\n".join(payload["decision_record"]["decisions"])

    assert "specified_language: python" in decisions
    assert "specified_framework: flask" in decisions


def test_diagnostics_include_project_specification(tmp_path):
    state = ProjectStateBuilder().build(
        workspace_path=tmp_path,
        request_text="Create a Flask application.",
    ).to_dict()
    result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="RuntimeError: static review failed",
    )

    analysis = FailureAnalyzer().analyze(tmp_path, result, project_state=state)

    assert analysis.evidence_pack["project_specification"]["framework"] == "flask"


def test_engineering_assessment_reports_specification_confidence(tmp_path):
    from studio.core.engineering_assessment import ConfidenceAssessor

    state = ProjectStateBuilder().build(
        workspace_path=tmp_path,
        request_text="Create a Flask application.",
    )
    observation = {
        "tests": {"count": 0},
        "run_metadata_files": [],
        "project_graph": state.project_graph,
        "project_state_summary": state.summary(),
    }

    assessment = ConfidenceAssessor().assess({"status": "queued"}, [], observation)

    assert assessment.evidence["project_specification"]["framework"] == "flask"
    assert any("Project specification exists" in reason for reason in assessment.reasons)


def test_run_api_exposes_project_specification():
    from studio.app import app
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run

    init_db()
    migrate()
    project_id = create_project("Spec API", "Create a Flask application.")
    run_id = create_run(project_id)

    response = app.test_client().get(f"/api/runs/{run_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["project_state"]["project_specification"]["framework"] == "flask"
    assert payload["project_state_summary"]["language"] == "python"


def test_unknown_request_remains_low_confidence_unknown():
    spec = build_project_specification("Make the thing nice.").to_dict()

    assert spec["language"] == "unknown"
    assert spec["framework"] == "unknown"
    assert spec["project_type"] == "unknown"
    assert spec["confidence"] < 0.5


def test_coder_prompt_includes_project_specification(monkeypatch):
    from studio.core import stages
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run

    prompts = {}

    class FakeAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            prompts.setdefault("user", user_prompt)
            return json.dumps(
                {
                    "schema_version": 1,
                    "project_summary": "Create app directory.",
                    "steps": [
                        {
                            "type": "create_directory",
                            "path": "app",
                            "purpose": "Application package",
                            "content_description": "Package directory",
                        }
                    ],
                }
            )

    init_db()
    migrate()
    project_id = create_project("Spec Prompt", "Create a Flask application.")
    run_id = create_run(project_id)
    monkeypatch.setattr(stages, "LLMAdapter", FakeAdapter)

    stages.run_coder_placeholder(run_id, "planner", "architect")

    assert "project_specification" in prompts["user"]
    assert '"framework": "flask"' in prompts["user"]
