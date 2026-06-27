from studio.core.fix_prompt import FixPromptBuilder, FixWorkspaceContextBuilder
from studio.core.tester_result import StageTestResult


def test_fix_prompt_contains_test_failure_and_original_output():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_main.py",
        stderr="TypeError: module object is not callable",
    )

    prompt = FixPromptBuilder().build(
        original_coder_output='[{"action":"write_file"}]',
        tester_result=tester_result,
    )

    assert "The generated project failed its tests." in prompt
    assert "FAILED tests/test_main.py" in prompt
    assert "TypeError: module object is not callable" in prompt
    assert "Original coder output:" in prompt
    assert "Return fix actions now." in prompt
    assert "ONLY Executor JSON actions" in prompt


def test_fix_prompt_mentions_supported_actions():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="boom",
    )

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
    )

    assert "mkdir" in prompt
    assert "write_file" in prompt
    assert "read_file" in prompt
    assert "run" in prompt


def test_fix_prompt_contains_module_callable_hint():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="TypeError: 'module' object is not callable",
        stderr="",
    )

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
    )

    assert "from app.main import main" in prompt
    assert "module" in prompt
    assert "not callable" in prompt


def test_fix_prompt_contains_unittest_import_hint():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="NameError: name 'unittest' is not defined",
        stderr="",
    )

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
    )

    assert "import unittest" in prompt
    assert "unittest.TestCase" in prompt


def test_fix_prompt_includes_relevant_workspace_files(tmp_path):
    app_dir = tmp_path / "app"
    tests_dir = tmp_path / "tests"
    app_dir.mkdir()
    tests_dir.mkdir()

    (app_dir / "calculator.py").write_text(
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('Cannot divide by zero')\n"
        "    return a / b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_calculator.py").write_text(
        "from app.calculator import divide, subtract\n\n"
        "def test_divide():\n"
        "    assert divide(6, 3) == 2\n"
        "    assert subtract(-6, -3) == -2\n",
        encoding="utf-8",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_calculator.py::test_divide",
        stderr="AssertionError: -3 != -2",
    )

    workspace_files = FixWorkspaceContextBuilder().build(tmp_path, tester_result)
    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
        task_description="Create a calculator package with divide(a, b).",
        workspace_files=workspace_files,
    )

    assert "Create a calculator package" in prompt
    assert "--- tests/test_calculator.py ---" in prompt
    assert "subtract(-6, -3)" in prompt
    assert "--- app/calculator.py ---" in prompt
    assert "def divide(a, b):" in prompt
    assert "You may fix implementation files, generated tests, or both." in prompt
