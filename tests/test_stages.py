from studio.core.stages import run_architect_placeholder
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, get_run


def test_run_architect_placeholder_saves_output_and_events():
    init_db()
    migrate()

    project_id = create_project(
        "Architect Placeholder Project",
        "Test architect placeholder",
    )
    run_id = create_run(project_id)

    output = run_architect_placeholder(run_id, "1. Build app")

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert "ARCHITECT PLACEHOLDER" in output
    assert run["current_stage"] == "architect"
    assert run["architect_output"] == output
    assert "architect_started" in event_types
    assert "architect_completed" in event_types


def test_run_coder_placeholder_saves_json_output_and_events(monkeypatch):
    from studio.core import stages
    from studio.core.stages import run_coder_placeholder

    class FakeLLMAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            return """
            [
              {
                "action": "mkdir",
                "path": "fake_llm_app"
              }
            ]
            """

    monkeypatch.setattr(stages, "LLMAdapter", FakeLLMAdapter)

    init_db()
    migrate()

    project_id = create_project(
        "Coder Placeholder Project",
        "Test coder placeholder",
    )
    run_id = create_run(project_id)

    output = run_coder_placeholder(
        run_id,
        "1. Build app",
        "Architecture plan",
    )

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert '"action": "mkdir"' in output
    assert '"path": "fake_llm_app"' in output
    assert run["current_stage"] == "coder"
    assert run["coder_output"] == output
    assert "coder_started" in event_types
    assert "coder_completed" in event_types


def test_run_executor_stage_executes_coder_json_in_workspace():
    from pathlib import Path

    from studio.config.settings import WORKSPACES_DIR
    from studio.core.stages import run_executor_stage

    init_db()
    migrate()

    project_id = create_project(
        "Executor Stage Project",
        "Test executor stage",
    )
    run_id = create_run(project_id)

    workspace = WORKSPACES_DIR / "executor-stage-test"
    workspace.mkdir(parents=True, exist_ok=True)

    coder_output = """
    [
      {
        "action": "mkdir",
        "path": "placeholder_app"
      }
    ]
    """

    results = run_executor_stage(run_id, str(workspace), coder_output)

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert results[0]["ok"] is True
    assert Path(workspace / "placeholder_app").exists()
    assert run["current_stage"] == "executor"
    assert "executor_started" in event_types
    assert "executor_completed" in event_types


def test_run_tester_stage_runs_pytest_in_workspace():
    from studio.config.settings import WORKSPACES_DIR
    from studio.core.stages import run_tester_stage

    init_db()
    migrate()

    project_id = create_project(
        "Tester Stage Project",
        "Test tester stage",
    )
    run_id = create_run(project_id)

    workspace = WORKSPACES_DIR / "tester-stage-test"
    app_dir = workspace / "app"
    tests_dir = workspace / "tests"

    app_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(
        "def main():\n" "    return 'hello'\n",
        encoding="utf-8",
    )

    (tests_dir / "test_main.py").write_text(
        "from app.main import main\n\n" "def test_main():\n" "    assert main() == 'hello'\n",
        encoding="utf-8",
    )

    result = run_tester_stage(run_id, str(workspace))

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert result["returncode"] == 0
    assert run["current_stage"] == "tester"
    assert run["tester_output"]
    assert "tester_started" in event_types
    assert "tester_completed" in event_types


def test_run_fix_stage_generates_fix_actions_without_execution(monkeypatch):
    from pathlib import Path

    from studio.core import stages
    from studio.core.stages import run_fix_stage
    from studio.core.tester_result import StageTestResult

    class FakeLLMAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            return """
            [
              {
                "action": "write_file",
                "path": "app/main.py",
                "content": "def main():\\n    return 'fixed'\\n"
              }
            ]
            """

    monkeypatch.setattr(stages, "LLMAdapter", FakeLLMAdapter)

    init_db()
    migrate()

    project_id = create_project(
        "Fix Stage Project",
        "Test fix stage",
    )
    run_id = create_run(project_id)

    workspace = Path(get_project(project_id)["workspace_path"])
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(
        "def main():\\n    return 'broken'\\n",
        encoding="utf-8",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="failed",
        stderr="assertion failed",
    )

    result = run_fix_stage(
        run_id,
        str(workspace),
        "original coder output",
        tester_result,
    )

    assert result["results"] is None
    assert "fixed" in result["output"]
    assert "broken" in (app_dir / "main.py").read_text(encoding="utf-8")

    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert "fix_started" in event_types
    assert "fix_generated" in event_types
    assert "fix_completed" in event_types


def test_run_architect_stage_saves_llm_output_and_events(monkeypatch):
    from studio.core import stages
    from studio.core.stages import run_architect_stage

    class FakeLLMAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            return "Project structure: app/main.py, tests/test_main.py"

    monkeypatch.setattr(stages, "LLMAdapter", FakeLLMAdapter)

    init_db()
    migrate()

    project_id = create_project(
        "LLM Architect Project",
        "Test LLM architect stage",
    )
    run_id = create_run(project_id)

    output = run_architect_stage(run_id, "1. Build app")

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert "Project structure" in output
    assert run["current_stage"] == "architect"
    assert run["architect_output"] == output
    assert "architect_started" in event_types
    assert "architect_completed" in event_types
