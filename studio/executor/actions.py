import json
import os
import subprocess
import sys
from pathlib import Path

from studio.config.settings import WORKSPACES_DIR
from studio.execution_model.program import ExecutorAction, ExecutorProgram


class ExecutorError(Exception):
    pass


def resolve_safe_path(workspace_path, relative_path):
    if not relative_path:
        raise ExecutorError("Path is required")

    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ExecutorError(f"Absolute paths are not allowed: {relative_path}")

    workspace = Path(workspace_path).resolve()
    target = (workspace / candidate).resolve()

    if target != workspace and workspace not in target.parents:
        raise ExecutorError(f"Path is outside workspace: {relative_path}")

    return target


def action_mkdir(workspace_path, path):
    target = resolve_safe_path(workspace_path, path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Directory created: {target}"


def action_write_file(workspace_path, path, content):
    target = resolve_safe_path(workspace_path, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"File written: {target}"


def action_read_file(workspace_path, path):
    target = resolve_safe_path(workspace_path, path)
    if not target.exists():
        raise ExecutorError(f"File does not exist: {path}")
    return target.read_text(encoding="utf-8")


def action_run(workspace_path, command, timeout=120):
    if not isinstance(command, str) or not command.strip():
        raise ExecutorError("Command is required")

    allowed_prefixes = [
        "pytest",
        "python -m pytest",
        "python -m unittest",
        "python3 -m pytest",
        "python3 -m unittest",
    ]

    normalized_command = command.strip()

    if not any(
        normalized_command == prefix or normalized_command.startswith(f"{prefix} ")
        for prefix in allowed_prefixes
    ):
        raise ExecutorError(f"Command is not allowed: {command}")

    if normalized_command.startswith("pytest"):
        normalized_command = f"{sys.executable} -m {normalized_command}"
    elif normalized_command.startswith("python -m "):
        normalized_command = f"{sys.executable} -m {normalized_command.removeprefix('python -m ')}"
    elif normalized_command.startswith("python3 -m "):
        normalized_command = f"{sys.executable} -m {normalized_command.removeprefix('python3 -m ')}"

    workspace = Path(workspace_path).resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace)

    result = subprocess.run(
        normalized_command,
        cwd=workspace,
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def execute_action(workspace_path, action):
    if isinstance(action, ExecutorAction):
        action = action.to_dict()

    action_type = action.get("action")

    if not workspace_path:
        raise ExecutorError("workspace_path is required")

    workspace = Path(workspace_path).resolve()

    workspace_root = WORKSPACES_DIR.resolve()

    if workspace != workspace_root and workspace_root not in workspace.parents:
        raise ExecutorError(f"Workspace is outside allowed root: {workspace}")

    if action_type == "mkdir":
        return action_mkdir(workspace_path, action["path"])

    if action_type == "write_file":
        return action_write_file(workspace_path, action["path"], action.get("content", ""))

    if action_type == "read_file":
        return action_read_file(workspace_path, action["path"])

    if action_type == "run":
        return action_run(
            workspace_path,
            action["command"],
            timeout=int(action.get("timeout", 120)),
        )

    raise ExecutorError(f"Unknown action: {action_type}")


def execute_actions(workspace_path, actions):
    program = ExecutorProgram.from_dicts(actions)
    results = []

    for action in program:
        action_dict = action.to_dict()
        try:
            output = execute_action(workspace_path, action)
            results.append(
                {
                    "ok": True,
                    "action": action_dict,
                    "output": output,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "action": action_dict,
                    "error": str(exc),
                }
            )
            break

    return results


def execute_actions_json(workspace_path, actions_json):
    try:
        actions = json.loads(actions_json)
    except json.JSONDecodeError as exc:
        raise ExecutorError(f"Invalid JSON: {exc}") from exc

    if not isinstance(actions, list):
        raise ExecutorError("Actions JSON must be a list.")

    return execute_actions(workspace_path, actions)
