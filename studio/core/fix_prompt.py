import re
from dataclasses import dataclass
from pathlib import Path

from studio.core.tester_result import StageTestResult

MAX_CONTEXT_FILES = 40
MAX_FILE_CHARS = 8_000
MAX_TREE_ENTRIES = 200

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "env",
    "venv",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
}


@dataclass(frozen=True)
class WorkspaceFileContext:
    path: str
    content: str


class FixWorkspaceContextBuilder:
    def build_tree(self, workspace_path: str | Path) -> str:
        workspace = Path(workspace_path)
        if not workspace.exists():
            return "Workspace path does not exist."

        entries = []
        for path in sorted(workspace.rglob("*")):
            if len(entries) >= MAX_TREE_ENTRIES:
                entries.append("... tree truncated ...")
                break

            if not self._is_allowed_context_path(workspace, path):
                continue

            relative_path = path.relative_to(workspace)
            suffix = "/" if path.is_dir() else ""
            entries.append(f"{relative_path.as_posix()}{suffix}")

        return "\n".join(entries) if entries else "Workspace is empty."

    def build(
        self,
        workspace_path: str | Path,
        tester_result: StageTestResult,
    ) -> list[WorkspaceFileContext]:
        workspace = Path(workspace_path)
        if not workspace.exists():
            return []

        candidate_paths = self._candidate_paths(workspace, tester_result)
        contexts: list[WorkspaceFileContext] = []

        for relative_path in candidate_paths[:MAX_CONTEXT_FILES]:
            full_path = workspace / relative_path
            if not self._is_safe_workspace_file(workspace, full_path):
                continue
            try:
                content = full_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            contexts.append(
                WorkspaceFileContext(
                    path=relative_path.as_posix(),
                    content=content[:MAX_FILE_CHARS],
                )
            )

        return contexts

    def _candidate_paths(self, workspace: Path, tester_result: StageTestResult) -> list[Path]:
        paths: list[Path] = []
        output = f"{tester_result.stdout}\n{tester_result.stderr}"

        file_pattern = r"(?:(?:FAILED|ERROR)\s+)?((?:tests|app)[/\\][\w./\\-]+\.py)"

        for raw_path in re.findall(file_pattern, output):
            self._append_unique(paths, Path(raw_path.replace("\\", "/")))

        for test_file in sorted((workspace / "tests").rglob("test*.py")):
            self._append_unique(paths, test_file.relative_to(workspace))

        for app_file in sorted((workspace / "app").rglob("*.py")):
            self._append_unique(paths, app_file.relative_to(workspace))

        return paths

    def _append_unique(self, paths: list[Path], path: Path) -> None:
        normalized = Path(*path.parts)
        if normalized not in paths:
            paths.append(normalized)

    def _is_safe_workspace_file(self, workspace: Path, path: Path) -> bool:
        try:
            resolved_workspace = workspace.resolve()
            resolved_path = path.resolve()
        except OSError:
            return False

        return (
            resolved_path.is_file()
            and resolved_path.suffix == ".py"
            and resolved_path.is_relative_to(resolved_workspace)
            and self._is_allowed_context_path(workspace, resolved_path)
        )

    def _is_allowed_context_path(self, workspace: Path, path: Path) -> bool:
        try:
            relative_path = path.resolve().relative_to(workspace.resolve())
        except (OSError, ValueError):
            return False

        if any(part in EXCLUDED_DIRS for part in relative_path.parts):
            return False

        return path.suffix not in EXCLUDED_SUFFIXES


class FixPromptBuilder:
    def build(
        self,
        original_coder_output: str,
        tester_result: StageTestResult,
        task_description: str | None = None,
        workspace_files: list[WorkspaceFileContext] | None = None,
        workspace_tree: str | None = None,
        bug_report: str | None = None,
        executor_output: str | None = None,
        repair_plan: str | None = None,
        trigger_stage: str = "tester_failed",
        static_review_output: str | None = None,
        rejected_actions: str | None = None,
        coder_raw_output: str | None = None,
        planner_output: str | None = None,
        architect_output: str | None = None,
        agent_context_json: str | None = None,
        protocol_summary: str | None = None,
        project_execution_contract: str | None = None,
        validation_report: str | None = None,
    ) -> str:
        workspace_context = self._format_workspace_files(workspace_files or [])
        task_context = task_description or "Not available."
        tree_context = workspace_tree or "No workspace tree was available."
        bug_context = bug_report or "No bug report was available."
        executor_context = executor_output or "No executor output was available."
        repair_context = repair_plan or "No repair plan was available."
        static_review_context = static_review_output or "No static review output was available."
        rejected_actions_context = rejected_actions or "No rejected built actions were provided."
        coder_raw_context = coder_raw_output or "No raw coder output was available."
        planner_context = planner_output or "No planner output was available."
        architect_context = architect_output or "No architect output was available."
        agent_context = agent_context_json or "No AgentContext was available."
        protocol_context = protocol_summary or "No protocol summary was available."
        execution_contract = (
            project_execution_contract or "No Project Execution Contract was available."
        )
        validation_context = validation_report or "No Validation Report was available."
        static_review_instructions = ""

        if trigger_stage == "static_review_failed":
            static_review_instructions = """
Static review repair mode:
- The workspace may be empty because executor has not run yet.
- Repair the rejected built actions by producing an Engineering Plan.
- Do not rely only on workspace files.
- Return a complete corrected Engineering Plan.
- Remove placeholder text and unsafe patterns from generated files.
""".strip()

        return f"""
The generated project failed validation or tests.
The generated project failed its tests.
The generated project failed its tests or static review.

You must return ONLY an Engineering Plan JSON object that implements the repair plan.
Do not explain anything.
Do not use markdown.
Use Validation Report violation IDs, severity, affected files, evidence, and repair_hint
as primary validation evidence.
Satisfy critical Validation Report violations before major or minor issues.

Agent Protocol:
{protocol_context}

AgentContext:
{agent_context}

Project Execution Contract:
{execution_contract}

Validation Report:
{validation_context}

Original task description:
{task_context}

Planner output:
{planner_context}

Architect output:
{architect_context}

Workspace tree:
{tree_context}

Trigger stage:
{trigger_stage}

Original coder output:
{original_coder_output}

Raw coder output:
{coder_raw_context}

Rejected built Executor actions:
{rejected_actions_context}

Static review output:
{static_review_context}

Current executor output:
{executor_context}

Current bug report:
{bug_context}

Repair plan:
{repair_context}

Repair strategy:
- Prioritize the repair plan primary_target.
- Repair production code before tests by default.
- If primary_target is an app/ file, include a create_file step for that file unless
  the repair plan clearly says the tests are wrong.
- Treat tests/ files as secondary targets.
- Modify tests only when the test assertion/import is wrong, requirements changed, or
  production-code repair cannot satisfy the original task.
- Keep production files and tests consistent; do not hide source bugs by weakening tests.

{static_review_instructions}

Test return code:
{tester_result.returncode}

Test stdout:
{tester_result.stdout}

Test stderr:
{tester_result.stderr}

Current relevant workspace files:
{workspace_context}

Rules:
- Return a JSON object with schema_version, project_summary, tests, and steps.
- Use only supported Engineering Plan step types:
  create_directory, create_file, run_command, run_tests.
- Prefer create_file steps to replace broken files.
- Implement the repair plan primary target before secondary targets.
- If implementation is correct and a generated test assertion is wrong, fix the test,
  but explain this choice only through the selected Engineering Plan steps.
- Do not invent package roots or import paths.
- Follow the Project Execution Contract for build, run, test, and module semantics.
- Treat the Project Execution Contract as protected unless traceback evidence proves it wrong.
- If the contract is wrong, repair the contract-aligned files and imports together.
- Base imports on the actual workspace tree and current file locations.
- Prefer repairing source files and tests consistently over overwriting tests blindly.
- Preserve the user's requested behavior from the original task.
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

Important Flask visual app readiness hints:
- If this is a simple Flask or visual smoke-test app, make it manually runnable with
  "python app/main.py" when app/main.py exists.
- Include if __name__ == "__main__": app.run(host="0.0.0.0", port=5000).
- If code uses redirect, url_for, or render_template_string, import those names from flask.
- Expose a real Flask app object named app.
- Tests should verify visible text and behavior, not only status code.
- For counter apps, verify Visual Smoke Test, Counter: 0, Increase, Reset, increase to
  Counter: 1, and reset back to Counter: 0.
- Add RUN.md with install, run, and open-browser instructions for visual apps.

Return the fix Engineering Plan now.
""".strip()

    def _format_workspace_files(self, workspace_files: list[WorkspaceFileContext]) -> str:
        if not workspace_files:
            return "No workspace files were available."

        sections = []
        for file_context in workspace_files:
            sections.append(f"--- {file_context.path} ---\n{file_context.content}")

        return "\n\n".join(sections)
