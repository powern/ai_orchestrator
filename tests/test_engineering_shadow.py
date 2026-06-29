import json

from studio.core.run_pipeline import RunPipeline
from studio.core.tester_result import StageTestResult
from studio.database.db import get_connection, init_db
from studio.database.migrations import migrate
from studio.services.engineering_service import (
    get_latest_engineering_assessment,
    record_engineering_shadow_assessment,
)
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, save_stage_output, update_run_status


def setup_database():
    init_db()
    migrate()


def count_rows(table_name):
    with get_connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return row["count"]


def test_shadow_assessment_persists_snapshot_and_events(monkeypatch):
    setup_database()
    monkeypatch.setenv("AI_ORCHESTRATOR_ENGINEERING_SHADOW", "1")
    sessions_before = count_rows("engineering_sessions")
    cycles_before = count_rows("engineering_cycles")
    snapshots_before = count_rows("project_state_snapshots")
    validation_before = count_rows("validation_results")
    project_id = create_project("Shadow", "Python app")
    project = dict(get_project(project_id))
    run_id = create_run(project_id)

    workspace = project["workspace_path"]
    from pathlib import Path

    Path(workspace, "app").mkdir(exist_ok=True)
    Path(workspace, "tests").mkdir(exist_ok=True)
    Path(workspace, "app", "main.py").write_text("def main():\n    return 'ok'\n")
    Path(workspace, "tests", "test_main.py").write_text("def test_ok():\n    assert True\n")
    Path(workspace, "RUN.md").write_text("Run: python app/main.py\n")

    save_stage_output(run_id, "executor_output", "ok")
    save_stage_output(run_id, "runtime_readiness", json.dumps({"manual_run_ready": True}))
    update_run_status(run_id, "completed", "tester_completed", "done")

    assessment = record_engineering_shadow_assessment(run_id, project)
    latest = get_latest_engineering_assessment(run_id)

    assert assessment is not None
    assert count_rows("engineering_sessions") == sessions_before + 1
    assert count_rows("engineering_cycles") == cycles_before + 1
    assert count_rows("project_state_snapshots") == snapshots_before + 1
    assert count_rows("validation_results") == validation_before + 1
    assert latest["decision"]["should_continue"] is False
    assert latest["observation"]["source_files"]["files"] == ["app/main.py"]
    assert latest["project_graph"]["summary"]["module_count"] == 1

    with get_connection() as conn:
        event_types = [
            row["event_type"]
            for row in conn.execute("SELECT event_type FROM run_events ORDER BY id")
        ]

    assert "engineering_observation_started" in event_types
    assert "engineering_observation_completed" in event_types
    assert "engineering_assessment_completed" in event_types


def test_run_detail_displays_engineering_assessment(monkeypatch):
    setup_database()
    monkeypatch.setenv("AI_ORCHESTRATOR_ENGINEERING_SHADOW", "1")
    from studio.app import app

    project_id = create_project("UI Shadow", "Python app")
    project = dict(get_project(project_id))
    run_id = create_run(project_id)
    update_run_status(run_id, "completed", "tester_completed", "done")
    record_engineering_shadow_assessment(run_id, project)

    response = app.test_client().get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert b"Engineering Assessment" in response.data
    assert b"Project Knowledge" in response.data
    assert b"Next Objective" in response.data


def test_run_api_exposes_project_graph(monkeypatch):
    setup_database()
    monkeypatch.setenv("AI_ORCHESTRATOR_ENGINEERING_SHADOW", "1")
    from studio.app import app

    project_id = create_project("API Graph", "Python app")
    project = dict(get_project(project_id))
    run_id = create_run(project_id)
    update_run_status(run_id, "completed", "tester_completed", "done")
    record_engineering_shadow_assessment(run_id, project)

    response = app.test_client().get(f"/api/runs/{run_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["project_graph"]["schema_version"] == 1
    assert payload["engineering_assessment"]["project_graph"]["schema_version"] == 1


def test_run_api_exposes_engineering_critic(monkeypatch):
    setup_database()
    from studio.app import app

    project_id = create_project("Critic API", "Python app")
    run_id = create_run(project_id)
    save_stage_output(
        run_id,
        "engineering_critic_output",
        json.dumps(
            {
                "status": "revision_required",
                "confidence": 0.82,
                "issues": [
                    {
                        "severity": "critical",
                        "type": "pass_only_tests",
                        "message": "Generated tests contain pass-only test cases.",
                    }
                ],
                "recommended_objective": "Replace placeholder tests.",
            }
        ),
    )

    response = app.test_client().get(f"/api/runs/{run_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["engineering_critic"]["status"] == "revision_required"


def test_run_detail_displays_engineering_critic(monkeypatch):
    setup_database()
    from studio.app import app

    project_id = create_project("Critic UI", "Python app")
    run_id = create_run(project_id)
    save_stage_output(
        run_id,
        "engineering_critic_output",
        json.dumps(
            {
                "status": "revision_required",
                "confidence": 0.82,
                "issues": [
                    {
                        "severity": "critical",
                        "type": "pass_only_tests",
                        "message": "Generated tests contain pass-only test cases.",
                    }
                ],
                "recommended_objective": "Replace placeholder tests.",
            }
        ),
    )

    response = app.test_client().get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert b"Engineering Critic" in response.data
    assert b"pass_only_tests" in response.data


def test_shadow_off_pipeline_does_not_store_engineering_assessment(monkeypatch, tmp_path):
    from studio.core import run_pipeline

    setup_database()
    monkeypatch.delenv("AI_ORCHESTRATOR_ENGINEERING_SHADOW", raising=False)
    sessions_before = count_rows("engineering_sessions")
    calls = {"tester": 0}
    project = {"workspace_path": str(tmp_path)}

    monkeypatch.setattr(run_pipeline, "run_architect_stage", lambda *_: "architect")
    monkeypatch.setattr(
        run_pipeline,
        "run_coder_placeholder",
        lambda *_: json.dumps(
            [
                {
                    "action": "write_file",
                    "path": "app/main.py",
                    "content": "def main():\n    return 'ok'\n",
                }
            ]
        ),
    )
    monkeypatch.setattr(run_pipeline.StaticReviewerAgent, "review", lambda *_: _review(True))
    monkeypatch.setattr(
        run_pipeline,
        "run_engineering_critic_stage",
        lambda *_, **__: _critic_result("approved"),
    )
    monkeypatch.setattr(run_pipeline, "run_executor_stage", lambda *_: [])

    def fake_tester(*_):
        calls["tester"] += 1
        return StageTestResult(success=True, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(run_pipeline, "run_tester_stage", fake_tester)
    monkeypatch.setattr(
        run_pipeline,
        "run_runtime_readiness_stage",
        lambda *_: (True, None),
    )
    monkeypatch.setattr(run_pipeline, "update_run_status", lambda *_, **__: None)
    monkeypatch.setattr(run_pipeline, "publish_run_event", lambda *_, **__: None)

    RunPipeline(lambda *_: "planner").execute(1, project)

    assert calls["tester"] == 1
    assert count_rows("engineering_sessions") == sessions_before


class _review:
    def __init__(self, approved):
        self.approved = approved
        self.summary = "ok"
        self.score = 1.0
        self.findings = []


class _critic_result:
    def __init__(self, status):
        self.status = status

    def to_json(self):
        return json.dumps({"status": self.status})
