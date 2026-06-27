from studio.core.bug_report import BugReportBuilder
from studio.core.tester_result import StageTestResult


def test_bug_report_contains_pytest_failure_details():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_main.py",
        stderr="TypeError: module object is not callable",
    )

    report = BugReportBuilder().build(tester_result)

    assert "Generated project tests failed." in report
    assert "Return code:" in report
    assert "FAILED tests/test_main.py" in report
    assert "TypeError: module object is not callable" in report
    assert "ONLY Executor JSON actions" in report


def test_bug_report_contains_import_error():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="TypeError: 'module' object is not callable",
    )

    report = BugReportBuilder().build(tester_result)

    assert "TypeError" in report
    assert "module" in report
    assert "Fix the generated project" in report
