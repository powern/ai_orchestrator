import json
import os
import subprocess
import sys
from pathlib import Path

from studio.config.settings import WORKSPACES_DIR


class ExecutorError(Exception):
    pass


def resolve_safe_path(workspace_path, relative_path):
    workspace = Path(workspace_path).resolve()
    target = (workspace / relative_path).resolve()

    if not str(target).startswith(str(workspace)):
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
    allowed_prefixes = [
        "pytest",
        "python -m pytest",
        "python -m",
    ]

    if not any(command.startswith(prefix) for prefix in allowed_prefixes):
        raise ExecutorError(f"Command is not allowed: {command}")

    if command.startswith("pytest"):
        command = f"{sys.executable} -m " + command

    workspace = Path(workspace_path).resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace)

    result = subprocess.run(
        command,
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
    action_type = action.get("action")

    if not workspace_path:
        raise ExecutorError("workspace_path is required")

    workspace = Path(workspace_path).resolve()

    if not str(workspace).startswith(str(WORKSPACES_DIR.resolve())):
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
    results = []

    for action in actions:
        try:
            output = execute_action(workspace_path, action)
            results.append({
                "ok": True,
                "action": action,
                "output": output,
            })
        except Exception as exc:
            results.append({
                "ok": False,
                "action": action,
                "error": str(exc),
            })
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
