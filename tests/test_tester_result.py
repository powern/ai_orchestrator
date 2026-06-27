from studio.core.tester_result import StageTestResult


def test_tester_result_from_successful_executor_result():
    result = StageTestResult.from_executor_result(
        {
            "returncode": 0,
            "stdout": "1 passed",
            "stderr": "",
        }
    )

    assert result.success is True
    assert result.returncode == 0
    assert result.stdout == "1 passed"
    assert result.stderr == ""


def test_tester_result_from_failed_executor_result():
    result = StageTestResult.from_executor_result(
        {
            "returncode": 1,
            "stdout": "",
            "stderr": "ModuleNotFoundError",
        }
    )

    assert result.success is False
    assert result.returncode == 1
    assert "ModuleNotFoundError" in result.stderr


def test_stage_test_result_supports_dict_style_access():
    result = StageTestResult(
        success=True,
        returncode=0,
        stdout="ok",
        stderr="",
    )

    assert result["success"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "ok"
