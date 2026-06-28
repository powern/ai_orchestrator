import pytest

from studio.core.executor_schema import (
    ExecutorSchemaValidationError,
    validate_executor_actions,
)


def test_invalid_mkdir_path_type_fails_schema_validation():
    actions = [
        {
            "action": "mkdir",
            "path": {
                "action": "mkdir",
                "path": "app",
            },
        }
    ]

    with pytest.raises(ExecutorSchemaValidationError, match="mkdir.path expected str, got dict"):
        validate_executor_actions(actions)


def test_invalid_run_command_type_fails_schema_validation():
    actions = [
        {
            "action": "run",
            "command": {
                "action": "run",
                "command": "pytest",
            },
        }
    ]

    with pytest.raises(ExecutorSchemaValidationError, match="run.command expected str, got dict"):
        validate_executor_actions(actions)


def test_unknown_action_fails_schema_validation():
    with pytest.raises(ExecutorSchemaValidationError, match="Unknown executor action: delete"):
        validate_executor_actions([{"action": "delete", "path": "app"}])


def test_path_traversal_fails_schema_validation():
    with pytest.raises(
        ExecutorSchemaValidationError,
        match="write_file.path must not contain traversal",
    ):
        validate_executor_actions(
            [
                {
                    "action": "write_file",
                    "path": "../app.py",
                    "content": "x",
                }
            ]
        )
