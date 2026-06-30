import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

SUPPORTED_STEP_TYPES = {
    "create_directory",
    "create_file",
    "run_command",
    "run_tests",
}


@dataclass(frozen=True)
class EngineeringPlanStep:
    type: str
    path: str | None = None
    purpose: str = ""
    content_description: str = ""
    content: str | None = None
    command: str | None = None
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.type,
            "purpose": self.purpose,
            "content_description": self.content_description,
            "depends_on": self.depends_on,
        }
        if self.path is not None:
            payload["path"] = self.path
        if self.content is not None:
            payload["content"] = self.content
        if self.command is not None:
            payload["command"] = self.command
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EngineeringPlanStep":
        return cls(
            type=value.get("type") or "",
            path=value.get("path"),
            purpose=value.get("purpose") or "",
            content_description=value.get("content_description") or "",
            content=value.get("content"),
            command=value.get("command"),
            depends_on=list(value.get("depends_on") or []),
        )


@dataclass(frozen=True)
class EngineeringPlan:
    schema_version: int = 1
    project_summary: str = ""
    steps: list[EngineeringPlanStep] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)
    tests: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_summary": self.project_summary,
            "dependencies": self.dependencies,
            "runtime": self.runtime,
            "tests": self.tests,
            "steps": [step.to_dict() for step in self.steps],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EngineeringPlan":
        return cls(
            schema_version=int(value.get("schema_version") or 1),
            project_summary=value.get("project_summary") or "",
            dependencies=list(value.get("dependencies") or []),
            runtime=dict(value.get("runtime") or {}),
            tests=dict(value.get("tests") or {}),
            steps=[
                EngineeringPlanStep.from_dict(item)
                for item in value.get("steps") or []
                if isinstance(item, dict)
            ],
        )


class EngineeringPlanValidationError(ValueError):
    def __init__(self, message: str, invalid_plan: Any | None = None):
        super().__init__(message)
        self.invalid_plan = invalid_plan


def parse_engineering_plan(text: str) -> EngineeringPlan:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EngineeringPlanValidationError(f"Invalid Engineering Plan JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise EngineeringPlanValidationError(
            "Engineering Plan root must be an object, not Executor JSON actions.",
            payload,
        )

    plan = EngineeringPlan.from_dict(payload)
    validate_engineering_plan(plan)
    return plan


def validate_engineering_plan(plan: EngineeringPlan) -> None:
    if plan.schema_version != 1:
        raise EngineeringPlanValidationError(
            f"Unsupported Engineering Plan schema_version: {plan.schema_version}",
            plan.to_dict(),
        )
    if not plan.steps:
        raise EngineeringPlanValidationError("Engineering Plan must contain at least one step.")

    for index, step in enumerate(plan.steps):
        if step.type not in SUPPORTED_STEP_TYPES:
            raise EngineeringPlanValidationError(
                f"Unsupported Engineering Plan step type at index {index}: {step.type}",
                plan.to_dict(),
            )
        if step.type in {"create_directory", "create_file"}:
            _validate_path(step.path, index)
        if step.type == "create_file" and step.content is None:
            raise EngineeringPlanValidationError(
                f"create_file step at index {index} must include content.",
                plan.to_dict(),
            )
        if step.type == "run_command" and not step.command:
            raise EngineeringPlanValidationError(
                f"run_command step at index {index} must include command.",
                plan.to_dict(),
            )


def _validate_path(path: str | None, index: int) -> None:
    if not isinstance(path, str) or not path:
        raise EngineeringPlanValidationError(f"Step at index {index} must include path.")
    normalized = path.replace("\\", "/")
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(path).is_absolute():
        raise EngineeringPlanValidationError(f"Step path must be relative: {path}")
    if ".." in PurePosixPath(normalized).parts:
        raise EngineeringPlanValidationError(f"Step path must stay inside workspace: {path}")
