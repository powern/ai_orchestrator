from pathlib import Path

from studio.core.agent import BaseAgent
from studio.reviewer.result import ReviewerResult


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    def process(self, workspace_path: str) -> ReviewerResult:
        workspace = Path(workspace_path)

        findings = []

        expected_files = [
            "app/main.py",
            "tests/test_main.py",
        ]

        for relative_path in expected_files:
            if not (workspace / relative_path).exists():
                findings.append(f"Missing expected file: {relative_path}")

        for path in workspace.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")

            if "Hello, World!" in text:
                findings.append(f"Placeholder text found in {path.relative_to(workspace)}")

            if "TODO" in text:
                findings.append(f"TODO found in {path.relative_to(workspace)}")

            if "pass" in text:
                findings.append(f"pass statement found in {path.relative_to(workspace)}")

        score = max(0, 100 - len(findings) * 20)

        return ReviewerResult(
            score=score,
            summary="Automatic deterministic review completed.",
            findings=findings,
            approved=score >= 80,
        )

    def review(self, workspace_path: str) -> ReviewerResult:
        return self.run(workspace_path)
