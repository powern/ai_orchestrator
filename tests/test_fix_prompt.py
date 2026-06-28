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
    workspace_tree = FixWorkspaceContextBuilder().build_tree(tmp_path)
    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
        task_description="Create a calculator package with divide(a, b).",
        workspace_files=workspace_files,
        workspace_tree=workspace_tree,
        bug_report="Bug report body",
        executor_output="Executor wrote project files",
    )

    assert "Create a calculator package" in prompt
    assert "Workspace tree:" in prompt
    assert "app/calculator.py" in prompt
    assert "--- tests/test_calculator.py ---" in prompt
    assert "subtract(-6, -3)" in prompt
    assert "--- app/calculator.py ---" in prompt
    assert "def divide(a, b):" in prompt
    assert "Bug report body" in prompt
    assert "Executor wrote project files" in prompt
    assert "Repair production code before tests by default." in prompt
    assert "Treat tests/ files as secondary targets." in prompt


def test_fix_prompt_prioritizes_repair_plan_primary_target():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_analyzer.py",
        stderr="AssertionError",
    )

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
        repair_plan=(
            '{\n'
            '  "root_cause": "app/application/analyzer.py",\n'
            '  "primary_target": "app/application/analyzer.py",\n'
            '  "repair_targets": ["app/application/analyzer.py"],\n'
            '  "secondary_targets": ["tests/test_analyzer.py"]\n'
            "}"
        ),
    )

    assert '"primary_target": "app/application/analyzer.py"' in prompt
    assert "Prioritize the repair plan primary_target." in prompt
    assert "Implement the repair plan primary target before secondary targets." in prompt
    assert "Modify tests only when the test assertion/import is wrong" in prompt


def test_fix_workspace_context_excludes_cache_and_includes_nested_python(tmp_path):
    app_dir = tmp_path / "app"
    nested_dir = app_dir / "application"
    cache_dir = nested_dir / "__pycache__"
    tests_dir = tmp_path / "tests"
    nested_dir.mkdir(parents=True)
    cache_dir.mkdir()
    tests_dir.mkdir()

    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (nested_dir / "calculator.py").write_text(
        "class Calculator:\n    pass\n",
        encoding="utf-8",
    )
    (cache_dir / "ignored.py").write_text("SHOULD_NOT_APPEAR = True\n", encoding="utf-8")
    (cache_dir / "ignored.pyc").write_bytes(b"\x00\x00")
    (tests_dir / "test_calculator.py").write_text(
        "from application.main import main\n",
        encoding="utf-8",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="ERROR tests/test_calculator.py",
        stderr="ModuleNotFoundError: No module named 'application.main'",
    )

    context_builder = FixWorkspaceContextBuilder()
    workspace_files = context_builder.build(tmp_path, tester_result)
    workspace_tree = context_builder.build_tree(tmp_path)

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
        workspace_files=workspace_files,
        workspace_tree=workspace_tree,
    )

    assert "app/application/calculator.py" in workspace_tree
    assert "app/application/__pycache__" not in workspace_tree
    assert "ignored.pyc" not in prompt
    assert "SHOULD_NOT_APPEAR" not in prompt
    assert "--- app/application/calculator.py ---" in prompt
