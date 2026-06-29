import json
from pathlib import Path
from types import SimpleNamespace

from studio.config.settings import CODER_MAX_OUTPUT_RETRIES, FIX_MAX_OUTPUT_RETRIES
from studio.core import run_pipeline, stages
from studio.core.stages import run_coder_placeholder, run_fix_stage
from studio.core.tester_result import StageTestResult
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, get_run, save_stage_output

VALID_ACTIONS = [
    {
        "action": "write_file",
        "path": "app/main.py",
        "content": "def main():\n    return 'ok'\n",
    }
]


class RecordingAdapter:
    def __init__(self):
        self.calls = 0
        self.prompts = []

    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        self.calls += 1
        self.prompts.append(user_prompt)
        return json.dumps([{"action": "write_file", "path": "app/main.py", "content": "raw"}])


class RetrySchemaSanitizer:
    calls = 0

    def __init__(self, adapter, model):
        pass

    def process(self, coder_output, max_attempts=2):
        type(self).calls += 1
        if type(self).calls == 1:
            return SimpleNamespace(
                actions=[
                    {
                        "action": "mkdir",
                        "path": {
                            "action": "mkdir",
                            "path": "app",
                        },
                    }
                ],
                attempts=1,
                retried=False,
                program=SimpleNamespace(to_dicts=lambda: []),
            )

        return SimpleNamespace(
            actions=VALID_ACTIONS,
            attempts=2,
            retried=True,
            program=SimpleNamespace(to_dicts=lambda: VALID_ACTIONS),
        )


class AlwaysInvalidSchemaSanitizer:
    def __init__(self, adapter, model):
        pass

    def process(self, coder_output, max_attempts=2):
        return SimpleNamespace(
            actions=[
                {
                    "action": "run",
                    "command": {
                        "action": "run",
                        "command": "pytest",
                    },
                }
            ],
            attempts=1,
            retried=False,
            program=SimpleNamespace(to_dicts=lambda: []),
        )


class UnsupportedActionThenValidSanitizer:
    calls = 0

    def __init__(self, adapter, model):
        pass

    def process(self, coder_output, max_attempts=2):
        type(self).calls += 1
        if type(self).calls == 1:
            return SimpleNamespace(
                actions=[
                    {
                        "action": "install_packages",
                        "packages": ["flask"],
                    }
                ],
                attempts=1,
                retried=False,
                program=SimpleNamespace(to_dicts=lambda: []),
            )

        return SimpleNamespace(
            actions=VALID_ACTIONS,
            attempts=2,
            retried=True,
            program=SimpleNamespace(to_dicts=lambda: VALID_ACTIONS),
        )


def create_schema_retry_run():
    init_db()
    migrate()
    project_id = create_project("Schema Retry Project", "Repair invalid executor schema")
    run_id = create_run(project_id)
    workspace = Path(get_project(project_id)["workspace_path"])
    save_stage_output(run_id, "coder_output", "[]")
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_main.py",
        stderr="AssertionError",
    )
    return run_id, workspace, tester_result


def test_coder_retries_after_executor_schema_validation_failure(monkeypatch):
    adapter = RecordingAdapter()
    RetrySchemaSanitizer.calls = 0
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)
    monkeypatch.setattr(stages, "ActionSanitizerAgent", RetrySchemaSanitizer)

    init_db()
    migrate()
    project_id = create_project("Coder Schema Retry Project", "Test")
    run_id = create_run(project_id)

    output = run_coder_placeholder(run_id, "plan", "architecture")

    event_types = [event["event_type"] for event in list_events(run_id)]

    assert output is not None
    assert event_types == [
        "coder_started",
        "agent_context_built",
        "coder_retry",
        "coder_sanitized",
        "coder_completed",
    ]
    assert "pipeline_failed" not in event_types
    assert "mkdir.path expected str, got dict" in adapter.prompts[-1]
    assert "Invalid sanitized actions:" in adapter.prompts[-1]


def test_coder_retry_rejects_unsupported_executor_action(monkeypatch):
    adapter = RecordingAdapter()
    UnsupportedActionThenValidSanitizer.calls = 0
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)
    monkeypatch.setattr(stages, "ActionSanitizerAgent", UnsupportedActionThenValidSanitizer)

    init_db()
    migrate()
    project_id = create_project("Coder Unsupported Action Retry Project", "Test")
    run_id = create_run(project_id)

    output = run_coder_placeholder(run_id, "plan", "architecture")

    event_types = [event["event_type"] for event in list_events(run_id)]
    retry_prompt = adapter.prompts[-1]

    assert output is not None
    assert "coder_retry" in event_types
    assert "Unknown executor action: install_packages" in retry_prompt
    assert "Supported actions are ONLY: mkdir, write_file, read_file, run" in retry_prompt
    assert "Replace unsupported actions such as install_packages" in retry_prompt
    assert "Do not invent new action types" in retry_prompt


def test_coder_fails_after_all_executor_schema_retries(monkeypatch):
    monkeypatch.setattr(stages, "LLMAdapter", RecordingAdapter)
    monkeypatch.setattr(stages, "ActionSanitizerAgent", AlwaysInvalidSchemaSanitizer)

    init_db()
    migrate()
    project_id = create_project("Coder Schema Fail Project", "Test")
    run_id = create_run(project_id)

    output = run_coder_placeholder(run_id, "plan", "architecture")

    run = get_run(run_id)
    event_types = [event["event_type"] for event in list_events(run_id)]

    assert output is None
    assert run["status"] == "failed"
    assert run["current_stage"] == "coder_failed"
    assert event_types.count("coder_retry") == CODER_MAX_OUTPUT_RETRIES
    assert "coder_failed" in event_types
    assert "run_failed" in event_types
    assert "coder_sanitized" not in event_types
    assert "pipeline_failed" not in event_types


def test_fix_retries_after_executor_schema_validation_failure(monkeypatch):
    adapter = RecordingAdapter()
    RetrySchemaSanitizer.calls = 0
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)
    monkeypatch.setattr(run_pipeline, "LLMAdapter", lambda: adapter)
    monkeypatch.setattr(run_pipeline, "ActionSanitizerAgent", RetrySchemaSanitizer)

    run_id, workspace, tester_result = create_schema_retry_run()
    fix_result = run_fix_stage(run_id, str(workspace), "[]", tester_result)

    sanitized_fix = run_pipeline.sanitize_fix_output_or_fail(
        run_id,
        fix_result["output"],
        str(workspace),
        "[]",
        tester_result,
    )

    event_types = [event["event_type"] for event in list_events(run_id)]
    fix_events = [event_type for event_type in event_types if event_type.startswith("fix_")]

    assert sanitized_fix is not None
    assert fix_events == [
        "fix_started",
        "fix_generated",
        "fix_retry",
        "fix_generated",
        "fix_sanitized",
        "fix_completed",
    ]
    assert event_types.index("fix_sanitized") < event_types.index("fix_completed")
    assert "pipeline_failed" not in event_types


def test_fix_fails_after_all_executor_schema_retries(monkeypatch):
    monkeypatch.setattr(stages, "LLMAdapter", RecordingAdapter)
    monkeypatch.setattr(run_pipeline, "LLMAdapter", RecordingAdapter)
    monkeypatch.setattr(run_pipeline, "ActionSanitizerAgent", AlwaysInvalidSchemaSanitizer)

    run_id, workspace, tester_result = create_schema_retry_run()
    fix_result = run_fix_stage(run_id, str(workspace), "[]", tester_result)

    sanitized_fix = run_pipeline.sanitize_fix_output_or_fail(
        run_id,
        fix_result["output"],
        str(workspace),
        "[]",
        tester_result,
    )

    run = get_run(run_id)
    event_types = [event["event_type"] for event in list_events(run_id)]

    assert sanitized_fix is None
    assert run["status"] == "failed"
    assert run["current_stage"] == "fix_failed"
    assert event_types.count("fix_retry") == FIX_MAX_OUTPUT_RETRIES
    assert "fix_failed" in event_types
    assert "run_failed" in event_types
    assert "fix_sanitized" not in event_types
    assert "fix_completed" not in event_types
    assert "pipeline_failed" not in event_types
