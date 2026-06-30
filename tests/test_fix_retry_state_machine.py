import json
from pathlib import Path

from studio.core import run_pipeline, stages
from studio.core.stages import run_fix_stage
from studio.core.tester_result import StageTestResult
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, get_run, save_stage_output

VALID_FIX_OUTPUT = json.dumps(
    {
        "schema_version": 1,
        "project_summary": "Repair app main.",
        "steps": [
            {
                "type": "create_file",
                "path": "app/main.py",
                "purpose": "Application entry point",
                "content_description": "Return fixed value",
                "content": "def main():\n    return 'fixed'\n",
            }
        ],
    }
)


def create_fix_run():
    init_db()
    migrate()
    project_id = create_project("Fix Retry Project", "Repair generated project")
    run_id = create_run(project_id)
    workspace = Path(get_project(project_id)["workspace_path"])
    (workspace / "app").mkdir(parents=True, exist_ok=True)
    (workspace / "app" / "main.py").write_text("def main():\n    return 'broken'\n")
    save_stage_output(run_id, "coder_output", "[]")
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_main.py",
        stderr="AssertionError: broken",
    )
    return run_id, workspace, tester_result


class RetryFixAdapter:
    def __init__(self):
        self.calls = 0
        self.retry_prompt = None

    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "schema_version": 1,
                    "steps": [
                        {
                            "type": "create_file",
                            "path": "app/main.py",
                            "purpose": "Missing content",
                        }
                    ],
                }
            )

        self.retry_prompt = user_prompt
        return VALID_FIX_OUTPUT


class AlwaysInvalidFixAdapter:
    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        return json.dumps(
            {
                "schema_version": 1,
                "steps": [
                    {
                        "type": "create_file",
                        "path": "app/main.py",
                        "purpose": "Still missing content",
                    }
                ],
            }
        )


def test_malformed_fix_output_retries_then_completes(monkeypatch):
    adapter = RetryFixAdapter()
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)

    run_id, workspace, tester_result = create_fix_run()
    fix_result = run_fix_stage(run_id, str(workspace), "[]", tester_result)

    sanitized_fix = run_pipeline.sanitize_fix_output_or_fail(
        run_id,
        fix_result["output"],
        str(workspace),
        "[]",
        tester_result,
    )

    event_types = [event["event_type"] for event in list_events(run_id)]

    assert sanitized_fix is not None
    fix_events = [event_type for event_type in event_types if event_type.startswith("fix_")]

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
    assert "Previous Fix Agent response could not be built." in adapter.retry_prompt
    assert "create_file step at index 0 must include content" in adapter.retry_prompt


def test_malformed_fix_output_fails_after_retries(monkeypatch):
    monkeypatch.setattr(stages, "LLMAdapter", lambda: AlwaysInvalidFixAdapter())

    run_id, workspace, tester_result = create_fix_run()
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
    assert event_types.count("fix_retry") == 2
    assert "fix_failed" in event_types
    assert "run_failed" in event_types
    assert "fix_completed" not in event_types
    assert "pipeline_failed" not in event_types


def test_fix_completed_never_precedes_fix_sanitized(monkeypatch):
    adapter = RetryFixAdapter()
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)

    run_id, workspace, tester_result = create_fix_run()
    fix_result = run_fix_stage(run_id, str(workspace), "[]", tester_result)
    run_pipeline.sanitize_fix_output_or_fail(
        run_id,
        fix_result["output"],
        str(workspace),
        "[]",
        tester_result,
    )

    event_types = [event["event_type"] for event in list_events(run_id)]

    assert "fix_completed" in event_types
    assert event_types.index("fix_sanitized") < event_types.index("fix_completed")


def test_missing_action_fix_output_regression_fails_without_pipeline_failed(monkeypatch):
    monkeypatch.setattr(stages, "LLMAdapter", lambda: AlwaysInvalidFixAdapter())

    run_id, workspace, tester_result = create_fix_run()
    fix_result = run_fix_stage(run_id, str(workspace), "[]", tester_result)
    run_pipeline.sanitize_fix_output_or_fail(
        run_id,
        fix_result["output"],
        str(workspace),
        "[]",
        tester_result,
    )

    event_types = [event["event_type"] for event in list_events(run_id)]

    assert "fix_retry" in event_types
    assert "fix_failed" in event_types
    assert "pipeline_failed" not in event_types
    assert "fix_completed" not in event_types
