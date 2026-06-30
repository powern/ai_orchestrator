from studio.contracts.execution import infer_execution_contract, validate_execution_contract
from studio.core.agent import BaseAgent
from studio.core.project_state import ProjectStateBuilder
from studio.execution_model.program import ExecutorProgram
from studio.reviewer.result import ReviewerResult

FLASK_HELPERS = ("redirect", "url_for", "render_template_string")


class StaticReviewerAgent(BaseAgent):
    name = "static_reviewer"

    def process(self, actions: list, project_state=None) -> ReviewerResult:
        findings = []
        program = ExecutorProgram.from_dicts(actions)

        seen_paths = set()
        raw_actions = [executor_action.to_dict() for executor_action in program]
        planned_files = [
            action.get("path")
            for action in raw_actions
            if action.get("action") == "write_file" and action.get("path")
        ]

        for action in raw_actions:
            action_type = action.get("action")
            path = action.get("path")

            if path:
                if path.startswith("/"):
                    findings.append(f"Absolute path is not allowed: {path}")

                if ".." in path.split("/"):
                    findings.append(f"Path traversal is not allowed: {path}")

                if path in seen_paths:
                    findings.append(f"Duplicate path action: {path}")

                seen_paths.add(path)

            if action_type == "write_file":
                content = action.get("content", "")

                if "Hello, World!" in content or "Hello, World!" in content.replace("\\'", "'"):
                    findings.append(f"Placeholder text found in {path}")

                if "TODO" in content:
                    findings.append(f"TODO found in {path}")

                if content.strip() == "pass":
                    findings.append(f"Suspicious pass-only file: {path}")

                findings.extend(self._review_flask_file(path, content))

            if action_type == "run":
                command = action.get("command", "")

                dangerous = [
                    "rm -rf",
                    "curl ",
                    "wget ",
                    "sudo ",
                    "chmod 777",
                ]

                for item in dangerous:
                    if item in command:
                        findings.append(f"Dangerous command found: {command}")

        state = project_state or ProjectStateBuilder().build(executor_actions=raw_actions)
        state_payload = state.to_dict() if hasattr(state, "to_dict") else state
        findings.extend(self._review_project_specification(state_payload))
        execution_contract = state_payload.get("execution_contract") or infer_execution_contract(
            executor_actions=raw_actions,
        ).to_dict()
        for violation in validate_execution_contract(
            execution_contract,
            planned_files=planned_files,
        ):
            if violation.code in {
                "missing_source_root",
                "missing_test_root",
                "missing_python_import_root",
            }:
                continue
            if violation.severity == "error":
                findings.append(f"Execution contract violation: {violation.message}")

        score = max(0, 100 - len(findings) * 20)

        critical_patterns = (
            "Absolute path",
            "Path traversal",
            "Dangerous command",
            "Placeholder text",
            "Flask app",
            "Flask helper",
            "Flask route",
        )

        approved = score >= 80 and not any(
            any(pattern in finding for pattern in critical_patterns) for finding in findings
        )

        return ReviewerResult(
            score=score,
            summary="Static action review completed.",
            findings=findings,
            approved=approved,
        )

    def review(self, actions: list, project_state=None) -> ReviewerResult:
        return self.process(actions, project_state=project_state)

    def _review_flask_file(self, path: str | None, content: str) -> list[str]:
        if not path or not path.endswith(".py") or not path.startswith("app"):
            return []

        findings = []
        uses_flask = "Flask(" in content or "@app.route" in content
        if not uses_flask:
            return findings

        if (
            "Flask(" in content
            and "from flask import" not in content
            and "import flask" not in content
        ):
            findings.append(f"Flask app uses Flask but does not import it in {path}")

        for helper in FLASK_HELPERS:
            if f"{helper}(" in content and not self._imports_flask_name(content, helper):
                findings.append(f"Flask helper {helper} used but not imported in {path}")

        if "@app.route" in content and "app = Flask(" not in content:
            findings.append(f"Flask route exists but app object is not defined in {path}")

        if self._is_visual_flask_entrypoint(path, content):
            if "app.run(" not in content:
                findings.append(f"Flask app is missing manual app.run entrypoint in {path}")
            elif "host=\"0.0.0.0\"" not in content or "port=5000" not in content:
                findings.append(
                    f"Flask app.run should use host=\"0.0.0.0\" and port=5000 in {path}"
                )

        return findings

    def _review_project_specification(self, project_state: dict) -> list[str]:
        specification = project_state.get("project_specification") or {}
        if specification.get("framework") != "flask":
            return []
        for item in (project_state.get("merged_files") or {}).get("files", []):
            if item.get("path") != "app/main.py":
                continue
            preview = item.get("content_preview", "")
            if "Flask(" not in preview and "@app.route" not in preview:
                return [
                    "Project specification mismatch: app/main.py does not match "
                    "requested framework."
                ]
        return []

    def _imports_flask_name(self, content: str, name: str) -> bool:
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("from flask import "):
                continue
            imported = stripped.removeprefix("from flask import ")
            names = {item.strip().split(" as ")[0] for item in imported.split(",")}
            if name in names:
                return True

        return False

    def _is_visual_flask_entrypoint(self, path: str, content: str) -> bool:
        return path in {"app/main.py", "app/app.py", "app.py"} and "@app.route" in content
