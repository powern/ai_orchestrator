from dataclasses import dataclass
from typing import Any

from studio.contracts.agent_outputs import CANONICAL_ACTIONS, FORBIDDEN_ALIASES


@dataclass(frozen=True)
class ProtocolViolation:
    code: str
    message: str
    severity: str = "warning"
    path: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.path:
            payload["path"] = self.path
        return payload


class ProtocolValidator:
    def validate_agent_context(self, context, stage: str) -> list[ProtocolViolation]:
        payload = context.to_dict() if hasattr(context, "to_dict") else context
        violations = []
        for section in ("task", "project", "pipeline", "evidence"):
            if section not in payload:
                violations.append(
                    ProtocolViolation(
                        "missing_context_section",
                        f"AgentContext is missing required section: {section}",
                        "error",
                        section,
                    )
                )

        task = payload.get("task", {})
        project = payload.get("project", {})
        if stage == "fix" and not task.get("original_user_request"):
            violations.append(
                ProtocolViolation(
                    "missing_original_user_request",
                    "Fix Agent context must include original_user_request.",
                    "error",
                    "task.original_user_request",
                )
            )
        workspace_state = project.get("workspace_state") or {}
        if workspace_state.get("exists") and not project.get("project_graph"):
            violations.append(
                ProtocolViolation(
                    "missing_project_graph",
                    "Project graph is missing even though workspace state is available.",
                    "warning",
                    "project.project_graph",
                )
            )
        return violations

    def validate_agent_output(self, output: Any, stage: str) -> list[ProtocolViolation]:
        del stage
        violations = []
        for path, key, value in self._walk(output):
            if key in FORBIDDEN_ALIASES:
                violations.append(
                    ProtocolViolation(
                        "forbidden_alias",
                        f"Forbidden output alias used: {key}",
                        "warning",
                        path,
                    )
                )
            if isinstance(value, dict):
                shorthand_keys = set(value) & CANONICAL_ACTIONS
                if "action" not in value and shorthand_keys:
                    violations.append(
                        ProtocolViolation(
                            "shorthand_action",
                            "Shorthand Executor action is forbidden.",
                            "warning",
                            path,
                        )
                    )
                action = value.get("action")
                if action is not None and action not in CANONICAL_ACTIONS:
                    violations.append(
                        ProtocolViolation(
                            "non_canonical_action",
                            f"Unsupported canonical Executor action: {action}",
                            "warning",
                            path,
                        )
                    )
        return violations

    def _walk(self, value: Any, path: str = "$"):
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = f"{path}.{key}"
                yield child_path, key, value
                yield from self._walk(item, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from self._walk(item, f"{path}[{index}]")
