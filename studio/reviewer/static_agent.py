from studio.core.agent import BaseAgent
from studio.execution_model.program import ExecutorProgram
from studio.reviewer.result import ReviewerResult

FLASK_HELPERS = ("redirect", "url_for", "render_template_string")


class StaticReviewerAgent(BaseAgent):
    name = "static_reviewer"

    def process(self, actions: list) -> ReviewerResult:
        findings = []
        program = ExecutorProgram.from_dicts(actions)

        seen_paths = set()

        for executor_action in program:
            action = executor_action.to_dict()
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

    def review(self, actions: list) -> ReviewerResult:
        return self.run(actions)

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
