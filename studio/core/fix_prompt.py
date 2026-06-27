from studio.core.tester_result import StageTestResult


class FixPromptBuilder:

    def build(self, original_coder_output: str, tester_result: StageTestResult) -> str:
        return f"""
The generated project failed its tests.

You must return ONLY Executor JSON actions that fix the existing workspace.
Do not explain anything.
Do not use markdown.

Original coder output:
{original_coder_output}

Test return code:
{tester_result.returncode}

Test stdout:
{tester_result.stdout}

Test stderr:
{tester_result.stderr}

Rules:
- Return a JSON array.
- Use only supported actions: mkdir, write_file, read_file, run.
- Prefer write_file actions to replace broken files.
- Do not delete files.
- Do not use absolute paths.
- Do not modify AI Studio itself.

Important Python fix hints:
- If tests contain "from app import main" and then call main(), fix the test to
  use "from app.main import main".
- If TypeError says "'module' object is not callable", it usually means the test
  imported a module instead of a function.
- If tests use unittest.TestCase, tests/test_main.py must contain "import unittest".
- If NameError says "name 'unittest' is not defined", add "import unittest" at
  the top of tests/test_main.py.
- Prefer fixing tests/test_main.py when the implementation in app/main.py is already correct.

Return fix actions now.
""".strip()
