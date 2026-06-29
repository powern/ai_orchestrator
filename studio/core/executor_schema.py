from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


class ExecutorSchemaValidationError(ValueError):
    def __init__(self, message: str, invalid_actions: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.invalid_actions = invalid_actions


SUPPORTED_ACTIONS = {"mkdir", "write_file", "read_file", "run"}


def validate_executor_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        raise ExecutorSchemaValidationError(
            f"Executor actions expected list, got {type(actions).__name__}",
        )

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ExecutorSchemaValidationError(
                f"action[{index}] expected object, got {type(action).__name__}",
                actions,
            )

        action_type = action.get("action")
        if not isinstance(action_type, str) or not action_type.strip():
            raise ExecutorSchemaValidationError(
                f"action[{index}].action expected non-empty str, got {type(action_type).__name__}",
                actions,
            )

        if action_type not in SUPPORTED_ACTIONS:
            raise ExecutorSchemaValidationError(f"Unknown executor action: {action_type}", actions)

        if action_type in {"mkdir", "read_file"}:
            _require_string_field(action, action_type, "path", actions)
            _validate_relative_path(action_type, action["path"], actions)
            continue

        if action_type == "write_file":
            _require_string_field(action, action_type, "path", actions)
            _require_string_field(action, action_type, "content", actions, allow_empty=True)
            _validate_relative_path(action_type, action["path"], actions)
            continue

        if action_type == "run":
            _require_string_field(action, action_type, "command", actions)
            working_directory = action.get("working_directory")
            if working_directory is not None:
                if not isinstance(working_directory, str):
                    raise ExecutorSchemaValidationError(
                        "run.working_directory expected str, "
                        f"got {type(working_directory).__name__}",
                        actions,
                    )
                _validate_relative_path(action_type, working_directory, actions)

            timeout = action.get("timeout")
            if timeout is not None and not isinstance(timeout, int):
                raise ExecutorSchemaValidationError(
                    f"run.timeout expected int, got {type(timeout).__name__}",
                    actions,
                )

    return actions


def _require_string_field(
    action: dict[str, Any],
    action_type: str,
    field_name: str,
    actions: list[dict[str, Any]],
    allow_empty: bool = False,
) -> None:
    if field_name not in action:
        raise ExecutorSchemaValidationError(f"{action_type}.{field_name} is required", actions)

    value = action[field_name]

    if not isinstance(value, str):
        raise ExecutorSchemaValidationError(
            f"{action_type}.{field_name} expected str, got {type(value).__name__}",
            actions,
        )

    if not allow_empty and not value.strip():
        raise ExecutorSchemaValidationError(
            f"{action_type}.{field_name} must not be empty",
            actions,
        )


def _validate_relative_path(
    action_type: str,
    path: str,
    actions: list[dict[str, Any]],
) -> None:
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        raise ExecutorSchemaValidationError(f"{action_type}.path must be relative: {path}", actions)

    parts = PurePosixPath(path.replace("\\", "/")).parts
    if ".." in parts:
        raise ExecutorSchemaValidationError(
            f"{action_type}.path must not contain traversal: {path}",
            actions,
        )
