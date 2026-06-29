import json
import re
from dataclasses import dataclass
from typing import Any

from studio.core.json_utils import normalize_coder_json
from studio.core.project_knowledge import ProjectKnowledgeGraphBuilder

CRITICAL = "critical"
MAJOR = "major"
MINOR = "minor"


@dataclass(frozen=True)
class CriticIssue:
    severity: str
    type: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "severity": self.severity,
            "type": self.type,
            "message": self.message,
        }
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class EngineeringCriticResult:
    status: str
    confidence: float
    issues: list[CriticIssue]
    recommended_objective: str
    project_graph: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "issues": [issue.to_dict() for issue in self.issues],
            "recommended_objective": self.recommended_objective,
            "project_graph": self.project_graph,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class EngineeringCritic:
    def review(
        self,
        original_request: str | None,
        planner_output: str | None,
        architect_output: str | None,
        coder_output: str,
        project_graph: dict[str, Any] | None = None,
        workspace_summary: dict[str, Any] | None = None,
    ) -> EngineeringCriticResult:
        del workspace_summary
        files = self._files_from_actions(coder_output)
        graph = project_graph or ProjectKnowledgeGraphBuilder().build_from_file_map(files)
        request_text = "\n".join(
            value or "" for value in (original_request, planner_output, architect_output)
        )
        issues = []
        issues.extend(self._placeholder_code_issues(files))
        issues.extend(self._placeholder_test_issues(files))
        issues.extend(self._hello_world_issues(files, request_text))
        issues.extend(self._lost_requirement_issues(files, request_text))
        issues.extend(self._runtime_behavior_issues(files, request_text, graph))
        issues.extend(self._knowledge_graph_issues(graph))

        critical_count = sum(1 for issue in issues if issue.severity == CRITICAL)
        status = "revision_required" if critical_count else "approved"
        confidence = 0.9 if issues else 0.96
        if critical_count:
            confidence = 0.82
        return EngineeringCriticResult(
            status=status,
            confidence=confidence,
            issues=issues,
            recommended_objective=self._recommended_objective(issues, graph),
            project_graph=graph,
        )

    def validate_result_schema(self, result: EngineeringCriticResult) -> None:
        payload = result.to_dict()
        if payload["status"] not in {"approved", "revision_required"}:
            raise ValueError("Engineering critic status is invalid.")
        if not isinstance(payload["confidence"], int | float):
            raise ValueError("Engineering critic confidence must be numeric.")
        if not isinstance(payload["issues"], list):
            raise ValueError("Engineering critic issues must be a list.")
        for issue in payload["issues"]:
            if issue.get("severity") not in {CRITICAL, MAJOR, MINOR}:
                raise ValueError("Engineering critic issue severity is invalid.")
            if not issue.get("type") or not issue.get("message"):
                raise ValueError("Engineering critic issue type and message are required.")
        if not payload["recommended_objective"]:
            raise ValueError("Engineering critic recommended objective is required.")

    def _files_from_actions(self, coder_output: str) -> dict[str, str]:
        files = {}
        for action in normalize_coder_json(coder_output):
            if action.get("action") == "write_file":
                files[action["path"]] = action.get("content", "")
        return files

    def _placeholder_code_issues(self, files: dict[str, str]) -> list[CriticIssue]:
        issues = []
        for path, content in files.items():
            if self._is_test(path):
                continue
            stripped = self._code_lines(content)
            lowered = content.lower()
            if not stripped:
                issues.append(
                    CriticIssue(
                        CRITICAL,
                        "empty_implementation",
                        "Generated source file is empty.",
                        path,
                    )
                )
            if any(token in lowered for token in ("todo", "fixme", "placeholder")):
                issues.append(
                    CriticIssue(
                        CRITICAL,
                        "placeholder_code",
                        "Generated source contains placeholder markers.",
                        path,
                    )
                )
            if stripped and all(line in {"pass", "..."} for line in stripped):
                issues.append(
                    CriticIssue(
                        CRITICAL,
                        "placeholder_implementation",
                        "Generated implementation contains only pass/ellipsis.",
                        path,
                    )
                )
        return issues

    def _placeholder_test_issues(self, files: dict[str, str]) -> list[CriticIssue]:
        issues = []
        for path, content in files.items():
            if not self._is_test(path):
                continue
            lines = self._code_lines(content)
            if not lines:
                issues.append(
                    CriticIssue(CRITICAL, "empty_tests", "Generated test file is empty.", path)
                )
            if "def test_" not in content and "unittest" not in content:
                issues.append(
                    CriticIssue(
                        CRITICAL,
                        "missing_test_cases",
                        "Generated tests define no test cases.",
                        path,
                    )
                )
            if self._has_pass_only_tests(content):
                issues.append(
                    CriticIssue(
                        CRITICAL,
                        "pass_only_tests",
                        "Generated tests contain pass-only test cases.",
                        path,
                    )
                )
        return issues

    def _hello_world_issues(self, files: dict[str, str], request_text: str) -> list[CriticIssue]:
        if "hello world" in request_text.lower():
            return []
        rich_terms = {
            "calculator",
            "counter",
            "flask",
            "fastapi",
            "route",
            "api",
            "temperature",
        }
        if not any(term in request_text.lower() for term in rich_terms):
            return []
        issues = []
        for path, content in files.items():
            if "hello world" in content.lower() or "hello, world" in content.lower():
                issues.append(
                    CriticIssue(
                        CRITICAL,
                        "hello_world_replacement",
                        "Implementation appears to replace requested behavior with Hello World.",
                        path,
                    )
                )
        return issues

    def _lost_requirement_issues(
        self,
        files: dict[str, str],
        request_text: str,
    ) -> list[CriticIssue]:
        expected_terms = self._expected_terms(request_text)
        if not expected_terms:
            return []
        combined = "\n".join(files.values()).lower()
        missing = [term for term in expected_terms if term not in combined]
        if not missing:
            return []
        return [
            CriticIssue(
                CRITICAL,
                "requirements_lost",
                "Generated implementation is missing requested behavior: " + ", ".join(missing),
            )
        ]

    def _runtime_behavior_issues(
        self,
        files: dict[str, str],
        request_text: str,
        graph: dict[str, Any],
    ) -> list[CriticIssue]:
        del files
        request_lower = request_text.lower()
        runtime_terms = ("flask", "web", "visual", "browser", "route")
        if not any(term in request_lower for term in runtime_terms):
            return []
        if graph["summary"]["entrypoint_count"] == 0:
            return [
                CriticIssue(
                    CRITICAL,
                    "missing_runtime_entrypoint",
                    "Runnable web project has no detected runtime entrypoint.",
                )
            ]
        if graph["summary"]["route_count"] == 0:
            return [
                CriticIssue(
                    CRITICAL,
                    "missing_runtime_behavior",
                    "Web project has no detected routes or handlers.",
                )
            ]
        return []

    def _knowledge_graph_issues(self, graph: dict[str, Any]) -> list[CriticIssue]:
        summary = graph.get("summary", {})
        if summary.get("route_count", 0) > 0 and summary.get("uncovered_routes", 0) > 0:
            return [
                CriticIssue(
                    MAJOR,
                    "weak_route_coverage",
                    "Project exposes routes that are not covered by generated tests.",
                )
            ]
        return []

    def _recommended_objective(self, issues: list[CriticIssue], graph: dict[str, Any]) -> str:
        if not issues:
            return "Proceed to static review."
        if any(issue.type == "requirements_lost" for issue in issues):
            return "Restore all requested behavior without simplifying the project."
        if any(issue.type in {"pass_only_tests", "empty_tests"} for issue in issues):
            return "Replace placeholder tests with behavioral assertions."
        if any(issue.type == "hello_world_replacement" for issue in issues):
            return "Replace Hello World output with the requested application behavior."
        if graph.get("summary", {}).get("uncovered_routes", 0) > 0:
            return "Add behavioral tests for uncovered routes."
        return "Revise implementation to address engineering quality findings."

    def _expected_terms(self, request_text: str) -> list[str]:
        terms = []
        lowered = request_text.lower()
        term_groups = {
            "calculator": ["add", "subtract", "multiply", "divide"],
            "counter": ["counter", "increase", "reset"],
            "temperature": ["temperature"],
            "flask": ["flask"],
            "fastapi": ["fastapi"],
        }
        for trigger, expected in term_groups.items():
            if trigger in lowered:
                terms.extend(expected)
        return sorted(set(terms))

    def _has_pass_only_tests(self, content: str) -> bool:
        test_pattern = r"def\s+test_[^(]*\([^)]*\):(?P<body>(?:\n[ \t]+[^\n]*)+)"
        for match in re.finditer(test_pattern, content):
            body_lines = self._code_lines(match.group("body"))
            if body_lines and all(line in {"pass", "..."} for line in body_lines):
                return True
        return False

    def _code_lines(self, content: str) -> list[str]:
        lines = []
        for line in content.splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            lines.append(value)
        return lines

    def _is_test(self, path: str) -> bool:
        name = path.rsplit("/", 1)[-1]
        return path.startswith("tests/") or name.startswith("test_")
