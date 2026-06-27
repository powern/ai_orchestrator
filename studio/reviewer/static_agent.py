from studio.core.agent import BaseAgent
from studio.execution_model.program import ExecutorProgram
from studio.reviewer.result import ReviewerResult


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

                if "Hello, World!" in content or "Hello, World!" in content.replace("\\'", "\'"):
                    findings.append(f"Placeholder text found in {path}")

                if "TODO" in content:
                    findings.append(f"TODO found in {path}")

                if content.strip() == "pass":
                    findings.append(f"Suspicious pass-only file: {path}")

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
        )

        approved = (
            score >= 80
            and not any(
                any(pattern in finding for pattern in critical_patterns)
                for finding in findings
            )
        )

        return ReviewerResult(
            score=score,
            summary="Static action review completed.",
            findings=findings,
            approved=approved,
        )

    def review(self, actions: list) -> ReviewerResult:
        return self.run(actions)
