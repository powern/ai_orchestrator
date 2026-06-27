import json
from pathlib import Path

from studio.core import run_pipeline, stages
from studio.core.stages import run_executor_stage, run_fix_stage, run_tester_stage
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.reviewer.static_agent import StaticReviewerAgent
from studio.services.project_service import create_project, get_project
from studio.services.run_service import get_run, save_stage_output


def test_fix_agent_can_repair_wrong_generated_calculator_test(monkeypatch):
    init_db()
    migrate()

    task_description = (
        "Create a small Python calculator package. Implement add, subtract, "
        "multiply, divide, and raise ValueError on division by zero."
    )
    project_id = create_project("GUI Acceptance Test 1", task_description)

    from studio.services.run_service import create_run

    run_id = create_run(project_id)
    workspace = Path(get_project(project_id)["workspace_path"])
    app_dir = workspace / "app"
    tests_dir = workspace / "tests"
    app_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    calculator_code = (
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def subtract(a, b):\n"
        "    return a - b\n\n"
        "def multiply(a, b):\n"
        "    return a * b\n\n"
        "def divide(a, b):\n"
        "    if b == 0:\n"
        '        raise ValueError("Cannot divide by zero")\n'
        "    return a / b\n"
    )
    bad_test_code = (
        "import unittest\n\n"
        "from app.calculator import add, divide, multiply, subtract\n\n\n"
        "class TestCalculator(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n\n"
        "    def test_subtract(self):\n"
        "        self.assertEqual(subtract(7, 3), 4)\n\n"
        "    def test_multiply(self):\n"
        "        self.assertEqual(multiply(4, 3), 12)\n\n"
        "    def test_divide(self):\n"
        "        self.assertEqual(divide(6, 3), 2)\n"
        "        self.assertEqual(subtract(-6, -3), -2)\n"
        "        self.assertEqual(divide(0, 1), 0)\n\n"
        "    def test_divide_by_zero(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            divide(1, 0)\n"
    )
    fixed_test_code = bad_test_code.replace(
        "self.assertEqual(subtract(-6, -3), -2)",
        "self.assertEqual(divide(-6, -3), 2)",
    )

    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "calculator.py").write_text(calculator_code, encoding="utf-8")
    (tests_dir / "test_calculator.py").write_text(bad_test_code, encoding="utf-8")

    original_coder_output = json.dumps(
        [
            {"action": "write_file", "path": "app/__init__.py", "content": ""},
            {"action": "write_file", "path": "app/calculator.py", "content": calculator_code},
            {"action": "write_file", "path": "tests/test_calculator.py", "content": bad_test_code},
        ],
        indent=2,
    )
    save_stage_output(run_id, "coder_output", original_coder_output)

    first_result = run_tester_stage(run_id, str(workspace))

    assert not first_result.success
    assert "subtract(-6, -3)" in first_result.stdout

    class FakeFixLLMAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            assert "Original task description:" in user_prompt
            assert "Create a small Python calculator package" in user_prompt
            assert "--- tests/test_calculator.py ---" in user_prompt
            assert "subtract(-6, -3)" in user_prompt
            assert "--- app/calculator.py ---" in user_prompt
            assert "def divide(a, b):" in user_prompt

            return json.dumps(
                [
                    {
                        "action": "write_file",
                        "path": "tests/test_calculator.py",
                        "content": fixed_test_code,
                    }
                ]
            )

    monkeypatch.setattr(stages, "LLMAdapter", FakeFixLLMAdapter)

    fix_result = run_fix_stage(
        run_id,
        str(workspace),
        original_coder_output,
        first_result,
    )

    class FakeSanitizerLLMAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            return fix_result["output"]

    monkeypatch.setattr(run_pipeline, "LLMAdapter", FakeSanitizerLLMAdapter)

    actions, normalized_fix_output = run_pipeline.sanitize_fix_output(run_id, fix_result["output"])
    static_review = StaticReviewerAgent().review(actions)

    assert static_review.approved
    assert "divide(-6, -3)" in normalized_fix_output

    run_executor_stage(run_id, str(workspace), normalized_fix_output)
    second_result = run_tester_stage(run_id, str(workspace))

    run = get_run(run_id)

    assert second_result.success
    assert "divide(-6, -3)" in (tests_dir / "test_calculator.py").read_text(encoding="utf-8")
    assert run["coder_output"] == original_coder_output
    assert "divide(-6, -3)" in run["fix_output"]
