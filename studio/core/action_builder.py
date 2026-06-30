import json
from pathlib import PurePosixPath
from typing import Any

from studio.contracts.engineering_plan import (
    EngineeringPlan,
    EngineeringPlanStep,
    parse_engineering_plan,
)
from studio.core.executor_schema import validate_executor_actions


class ActionBuilderError(ValueError):
    pass


class EngineeringPlanActionBuilder:
    def build(self, plan: EngineeringPlan) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        created_dirs: set[str] = set()

        for step in plan.steps:
            if step.type == "create_directory":
                self._append_mkdir(actions, created_dirs, step.path)
            elif step.type == "create_file":
                for directory in self._parent_directories(step):
                    self._append_mkdir(actions, created_dirs, directory)
                actions.append(
                    {
                        "action": "write_file",
                        "path": self._path(step.path),
                        "content": step.content or "",
                    }
                )
            elif step.type == "run_command":
                actions.append({"action": "run", "command": step.command or ""})
            elif step.type == "run_tests":
                actions.append({"action": "run", "command": self._test_command(plan)})
            else:
                raise ActionBuilderError(f"Unsupported Engineering Plan step type: {step.type}")

        validate_executor_actions(actions)
        return actions

    def to_json(self, plan: EngineeringPlan) -> str:
        return json.dumps(self.build(plan), ensure_ascii=False, indent=2)

    def _append_mkdir(
        self,
        actions: list[dict[str, Any]],
        created_dirs: set[str],
        path: str | None,
    ) -> None:
        directory = self._path(path)
        if not directory or directory in created_dirs:
            return
        actions.append({"action": "mkdir", "path": directory})
        created_dirs.add(directory)

    def _parent_directories(self, step: EngineeringPlanStep) -> list[str]:
        path = self._path(step.path)
        parent = PurePosixPath(path).parent
        if str(parent) in {"", "."}:
            return []
        parts = []
        current = PurePosixPath()
        for part in parent.parts:
            current = current / part
            parts.append(current.as_posix())
        return parts

    def _path(self, path: str | None) -> str:
        if not path:
            raise ActionBuilderError("Engineering Plan step is missing path.")
        return path.replace("\\", "/").strip("/")

    def _test_command(self, plan: EngineeringPlan) -> str:
        command = plan.tests.get("command") if isinstance(plan.tests, dict) else None
        return command or "pytest -q"


def build_actions_from_engineering_plan_text(text: str) -> tuple[list[dict[str, Any]], str]:
    plan = parse_engineering_plan(text)
    actions = EngineeringPlanActionBuilder().build(plan)
    return actions, plan.to_json()


def parse_executor_actions_json(text: str) -> list[dict[str, Any]]:
    try:
        actions = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ActionBuilderError(f"Invalid built Executor JSON: {exc}") from exc
    validate_executor_actions(actions)
    return actions
