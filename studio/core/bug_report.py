from studio.core.tester_result import StageTestResult


class BugReportBuilder:

    def build(self, tester_result: StageTestResult) -> str:
        return f"""
Generated project tests failed.

Return code:
{tester_result.returncode}

STDOUT:
{tester_result.stdout}

STDERR:
{tester_result.stderr}

Task:
Fix the generated project by returning ONLY Executor JSON actions.
Do not explain anything.
Do not use markdown.
""".strip()
