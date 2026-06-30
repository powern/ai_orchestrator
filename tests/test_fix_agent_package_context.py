import json
from pathlib import Path

from studio.core import run_pipeline, stages
from studio.core.stages import run_executor_stage, run_fix_stage, run_tester_stage
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.reviewer.static_agent import StaticReviewerAgent
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, get_run, save_stage_output


def test_fix_agent_uses_workspace_tree_for_nested_app_package_imports(monkeypatch):
    init_db()
    migrate()

    task_description = (
        "Create a Python application with app/main.py, a calculator domain, "
        "and tests for the calculator entrypoint."
    )
    project_id = create_project("Self Healing GUI Test 2", task_description)
    run_id = create_run(project_id)
    workspace = Path(get_project(project_id)["workspace_path"])

    (workspace / "app" / "application").mkdir(parents=True, exist_ok=True)
    (workspace / "app" / "domain").mkdir(parents=True, exist_ok=True)
    (workspace / "app" / "infrastructure").mkdir(parents=True, exist_ok=True)
    (workspace / "tests").mkdir(parents=True, exist_ok=True)
    (workspace / "app" / "application" / "__pycache__").mkdir(parents=True, exist_ok=True)

    (workspace / "app" / "__init__.py").write_text("", encoding="utf-8")
    (workspace / "app" / "main.py").write_text(
        "from application.calculator import Calculator\n"
        "from infrastructure.io import IO\n\n\n"
        "def main():\n"
        "    return Calculator().add(2, 3)\n",
        encoding="utf-8",
    )
    (workspace / "app" / "application" / "calculator.py").write_text(
        "from domain.temperature import Temperature\n\n\n"
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        Temperature()\n"
        "        return a + b\n",
        encoding="utf-8",
    )
    (workspace / "app" / "domain" / "temperature.py").write_text(
        "class Temperature:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (workspace / "app" / "infrastructure" / "io.py").write_text(
        "class IO:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (workspace / "tests" / "test_calculator.py").write_text(
        "from application.main import main\n\n\n"
        "def test_main():\n"
        "    assert main() == 5\n",
        encoding="utf-8",
    )
    (workspace / "app" / "application" / "__pycache__" / "calculator.pyc").write_bytes(
        b"ignored"
    )

    original_coder_output = json.dumps(
        [
            {"action": "write_file", "path": "app/main.py", "content": "bad imports"},
            {
                "action": "write_file",
                "path": "app/application/calculator.py",
                "content": "bad imports",
            },
            {
                "action": "write_file",
                "path": "tests/test_calculator.py",
                "content": "from application.main import main",
            },
        ],
        indent=2,
    )
    save_stage_output(run_id, "coder_output", original_coder_output)
    save_stage_output(run_id, "executor_output", "Executor created nested app package files.")

    first_result = run_tester_stage(run_id, str(workspace))

    assert not first_result.success
    assert (
        "ModuleNotFoundError" in first_result.stderr
        or "ModuleNotFoundError" in first_result.stdout
    )

    fixed_main = (
        "from app.application.calculator import Calculator\n"
        "from app.infrastructure.io import IO\n\n\n"
        "def main():\n"
        "    IO()\n"
        "    return Calculator().add(2, 3)\n"
    )
    fixed_calculator = (
        "from app.domain.temperature import Temperature\n\n\n"
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        Temperature()\n"
        "        return a + b\n"
    )
    fixed_test = (
        "from app.main import main\n\n\n"
        "def test_main():\n"
        "    assert main() == 5\n"
    )

    class FakeFixLLMAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            assert "Workspace tree:" in user_prompt
            assert "app/main.py" in user_prompt
            assert "app/application/calculator.py" in user_prompt
            assert "app/domain/temperature.py" in user_prompt
            assert "tests/test_calculator.py" in user_prompt
            assert "ModuleNotFoundError" in user_prompt
            assert "Executor created nested app package files." in user_prompt
            assert "No module named 'application" in user_prompt
            assert "from application.main import main" in user_prompt
            assert "Repair plan:" in user_prompt
            assert '"root_cause": "app/main.py"' in user_prompt
            assert '"repair_targets":' in user_prompt
            assert "__pycache__" not in user_prompt
            assert ".pyc" not in user_prompt

            return json.dumps(
                {
                    "schema_version": 1,
                    "project_summary": "Repair nested app package imports.",
                    "steps": [
                        {
                            "type": "create_file",
                            "path": "app/application/__init__.py",
                            "purpose": "Application package marker",
                            "content_description": "Make app.application importable",
                            "content": "",
                        },
                        {
                            "type": "create_file",
                            "path": "app/domain/__init__.py",
                            "purpose": "Domain package marker",
                            "content_description": "Make app.domain importable",
                            "content": "",
                        },
                        {
                            "type": "create_file",
                            "path": "app/infrastructure/__init__.py",
                            "purpose": "Infrastructure package marker",
                            "content_description": "Make app.infrastructure importable",
                            "content": "",
                        },
                        {
                            "type": "create_file",
                            "path": "app/main.py",
                            "purpose": "Application entry point",
                            "content_description": "Use app-rooted imports",
                            "content": fixed_main,
                        },
                        {
                            "type": "create_file",
                            "path": "app/application/calculator.py",
                            "purpose": "Calculator domain service",
                            "content_description": "Use app-rooted domain import",
                            "content": fixed_calculator,
                        },
                        {
                            "type": "create_file",
                            "path": "tests/test_calculator.py",
                            "purpose": "Entrypoint test",
                            "content_description": "Import main through app package root",
                            "content": fixed_test,
                        },
                    ],
                }
            )

    monkeypatch.setattr(stages, "LLMAdapter", FakeFixLLMAdapter)

    fix_result = run_fix_stage(
        run_id,
        str(workspace),
        original_coder_output,
        first_result,
    )

    actions, normalized_fix_output = run_pipeline.sanitize_fix_output(
        run_id,
        fix_result["output"],
    )
    static_review = StaticReviewerAgent().review(actions)

    assert static_review.approved
    assert "from app.main import main" in normalized_fix_output
    assert "from app.application.calculator import Calculator" in normalized_fix_output

    run_executor_stage(run_id, str(workspace), normalized_fix_output)
    second_result = run_tester_stage(run_id, str(workspace))
    run = get_run(run_id)

    assert second_result.success
    assert '"root_cause": "app/main.py"' in run["repair_plan"]
    assert '"root_cause": "app/main.py"' in run["failure_analysis"]
    assert run["fix_raw_output"]
    assert run["fix_output"]
