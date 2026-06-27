from studio.core.fix_prompt import FixPromptBuilder
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
