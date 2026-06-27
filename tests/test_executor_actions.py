from pathlib import Path

import pytest

from studio.config.settings import WORKSPACES_DIR
from studio.executor.actions import (
    ExecutorError,
    action_run,
    execute_actions,
    execute_actions_json,
    resolve_safe_path,
)


def make_workspace(name="executor-test-workspace"):
    workspace = WORKSPACES_DIR / name
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def test_executor_write_and_read_file_inside_workspace():
    workspace = make_workspace()

    results = execute_actions(
        str(workspace),
        [
            {
                "action": "write_file",
                "path": "tmp_executor_file.txt",
                "content": "hello executor",
            },
            {
                "action": "read_file",
                "path": "tmp_executor_file.txt",
            },
        ],
    )

    assert results[0]["ok"] is True
    assert results[1]["ok"] is True
    assert results[1]["output"] == "hello executor"

    Path(workspace / "tmp_executor_file.txt").unlink(missing_ok=True)


def test_executor_rejects_path_outside_workspace():
    workspace = make_workspace()

    with pytest.raises(ExecutorError):
        resolve_safe_path(str(workspace), "../../studio/app.py")


def test_executor_rejects_workspace_outside_allowed_root():
    results = execute_actions(
        "/tmp",
        [
            {
                "action": "write_file",
                "path": "x.txt",
                "content": "bad",
            }
        ],
    )

    assert results[0]["ok"] is False
    assert "Workspace is outside allowed root" in results[0]["error"]


def test_executor_rejects_unsafe_command():
    workspace = make_workspace()

    results = execute_actions(
        str(workspace),
        [
            {
                "action": "run",
                "command": "rm -rf /",
            }
        ],
    )

    assert results[0]["ok"] is False
    assert "not allowed" in results[0]["error"]


def test_executor_accepts_json_actions_inside_workspace():
    workspace = make_workspace("executor-json-workspace")

    results = execute_actions_json(
        str(workspace),
        """
        [
            {
                "action": "write_file",
                "path": "tmp_executor_json.txt",
                "content": "json ok"
            },
            {
                "action": "read_file",
                "path": "tmp_executor_json.txt"
            }
        ]
        """,
    )

    assert results[0]["ok"] is True
    assert results[1]["output"] == "json ok"

    Path(workspace / "tmp_executor_json.txt").unlink(missing_ok=True)


def test_action_run_sets_pythonpath_to_workspace(tmp_path):
    app_dir = tmp_path / "app"
    tests_dir = tmp_path / "tests"

    app_dir.mkdir()
    tests_dir.mkdir()

    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(
        "def main():\n    return 'hello'\n",
        encoding="utf-8",
    )

    (tests_dir / "test_main.py").write_text(
        "from app.main import main\n\n"
        "def test_main():\n"
        "    assert main() == 'hello'\n",
        encoding="utf-8",
    )

    result = action_run(str(tmp_path), "pytest -q")

    assert result["returncode"] == 0
    assert "1 passed" in result["stdout"]
