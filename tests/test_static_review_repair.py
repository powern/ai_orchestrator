import json

from studio.core import run_pipeline, stages
from studio.core.run_pipeline import RunPipeline
from studio.core.stages import run_fix_stage
from studio.core.tester_result import StageTestResult
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, get_run, save_stage_output

PLACEHOLDER_ACTIONS = json.dumps(
    [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print('Hello, World!')\n",
        },
        {
            "action": "write_file",
            "path": "tests/test_main.py",
            "content": "def test_main():\n    assert 'Hello, World!'\n",
        },
    ],
    indent=2,
)

FIXED_ACTIONS = json.dumps(
    [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "def main():\n    return 'fixed'\n",
        },
        {
            "action": "write_file",
            "path": "tests/test_main.py",
            "content": (
                "from app.main import main\n\n\n"
                "def test_main():\n"
                "    assert main() == 'fixed'\n"
            ),
        },
    ],
    indent=2,
)


def create_static_review_run():
    init_db()
    migrate()
    project_id = create_project("Static Review Repair", "Create a small Python app.")
    run_id = create_run(project_id)
    workspace = get_project(project_id)["workspace_path"]
    save_stage_output(run_id, "planner_output", "Build app/main.py and tests/test_main.py")
    save_stage_output(run_id, "architect_output", "Files: app/main.py, tests/test_main.py")
    save_stage_output(run_id, "coder_raw_output", PLACEHOLDER_ACTIONS)
    save_stage_output(run_id, "coder_output", PLACEHOLDER_ACTIONS)
    return project_id, run_id, workspace


def test_static_review_fix_prompt_uses_rejected_actions_context(monkeypatch):
    _, run_id, workspace = create_static_review_run()
    static_review_output = json.dumps(
        {
            "findings": [
                "Placeholder text found in app/main.py",
                "Placeholder text found in tests/test_main.py",
            ]
        },
        indent=2,
    )
    save_stage_output(
        run_id,
        "bug_report",
        "Static review rejected executor actions.\n"
        "Placeholder text found in app/main.py\n"
        "Placeholder text found in tests/test_main.py",
    )

    class FakeFixAdapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            assert "Trigger stage:\nstatic_review_failed" in user_prompt
            assert "The workspace may be empty because executor has not run yet." in user_prompt
            assert "Repair the rejected Executor JSON actions directly." in user_prompt
            assert "Do not rely only on workspace files." in user_prompt
            assert "Return a complete corrected Executor JSON action list." in user_prompt
            assert "Rejected Executor actions:" in user_prompt
            assert "print('Hello, World!')" in user_prompt
            assert "Static review output:" in user_prompt
            assert "Placeholder text found in app/main.py" in user_prompt
            assert "Planner output:" in user_prompt
            assert "Build app/main.py" in user_prompt
            assert "Architect output:" in user_prompt
            assert "Files: app/main.py" in user_prompt
            assert '"primary_target": "app/main.py"' in user_prompt
            return FIXED_ACTIONS

    monkeypatch.setattr(stages, "LLMAdapter", FakeFixAdapter)

    result = run_fix_stage(
        run_id,
        workspace,
        PLACEHOLDER_ACTIONS,
        StageTestResult(
            success=False,
            returncode=1,
            stdout="Static review rejected executor actions.",
            stderr="Placeholder text found in app/main.py\n"
            "Placeholder text found in tests/test_main.py",
        ),
        trigger_stage="static_review_failed",
        static_review_output=static_review_output,
        rejected_actions=PLACEHOLDER_ACTIONS,
    )

    events = list_events(run_id)
    fix_started = next(event for event in events if event["event_type"] == "fix_started")

    assert result["output"] == FIXED_ACTIONS
    assert "after static_review_failed" in fix_started["message"]
    assert "after tester failure" not in fix_started["message"]


def fake_sanitize(run_id, fix_output):
    actions = json.loads(fix_output)
    normalized = json.dumps(actions, indent=2)
    save_stage_output(run_id, "fix_output", normalized)
    run_pipeline.add_event(
        run_id,
        "fix_sanitized",
        "static_reviewer",
        "Fix output sanitized to Executor JSON.",
        normalized,
    )
    return actions, normalized


def test_static_review_fix_success_runs_executor_and_tester(monkeypatch):
    project_id, run_id, workspace = create_static_review_run()
    project = {"id": project_id, "workspace_path": workspace}

    def fake_planner(run_id, project):
        return "planner"

    def fake_architect(run_id, planner_output):
        return "architect"

    def fake_coder(run_id, planner_output, architect_output):
        run_pipeline.add_event(
            run_id,
            "coder_sanitized",
            "coder",
            "Coder output sanitized to Executor JSON.",
            PLACEHOLDER_ACTIONS,
        )
        return PLACEHOLDER_ACTIONS

    def fake_fix(*args, **kwargs):
        assert kwargs["trigger_stage"] == "static_review_failed"
        assert "Placeholder text found in app/main.py" in kwargs["static_review_output"]
        assert "Hello, World!" in kwargs["rejected_actions"]
        return {"output": FIXED_ACTIONS, "results": None}

    def fake_tester(run_id, workspace_path):
        run_pipeline.add_event(run_id, "tester_started", "tester", "Tester stage started.")
        return StageTestResult(success=True, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(run_pipeline, "run_architect_stage", fake_architect)
    monkeypatch.setattr(run_pipeline, "run_coder_placeholder", fake_coder)
    monkeypatch.setattr(run_pipeline, "run_fix_stage", fake_fix)
    monkeypatch.setattr(run_pipeline, "sanitize_fix_output", fake_sanitize)
    monkeypatch.setattr(run_pipeline, "run_tester_stage", fake_tester)

    RunPipeline(fake_planner).execute(run_id, project)

    event_types = [event["event_type"] for event in list_events(run_id)]

    assert event_types.index("coder_sanitized") < event_types.index("static_review_failed")
    assert event_types.index("static_review_failed") < event_types.index("fix_sanitized")
    assert "fix_completed" in event_types
    assert "static_review_completed_after_fix" in event_types
    assert "executor_started" in event_types
    assert "tester_started" in event_types
    assert "pipeline_failed" not in event_types


def test_static_review_fix_failure_fails_without_pipeline_failed(monkeypatch):
    project_id, run_id, workspace = create_static_review_run()
    project = {"id": project_id, "workspace_path": workspace}

    def fake_planner(run_id, project):
        return "planner"

    def fake_architect(run_id, planner_output):
        return "architect"

    def fake_coder(run_id, planner_output, architect_output):
        run_pipeline.add_event(
            run_id,
            "coder_sanitized",
            "coder",
            "Coder output sanitized to Executor JSON.",
            PLACEHOLDER_ACTIONS,
        )
        return PLACEHOLDER_ACTIONS

    def fake_fix(*args, **kwargs):
        return {"output": PLACEHOLDER_ACTIONS, "results": None}

    monkeypatch.setattr(run_pipeline, "run_architect_stage", fake_architect)
    monkeypatch.setattr(run_pipeline, "run_coder_placeholder", fake_coder)
    monkeypatch.setattr(run_pipeline, "run_fix_stage", fake_fix)
    monkeypatch.setattr(run_pipeline, "sanitize_fix_output", fake_sanitize)

    RunPipeline(fake_planner).execute(run_id, project)

    run = get_run(run_id)
    event_types = [event["event_type"] for event in list_events(run_id)]

    assert run["status"] == "failed"
    assert run["current_stage"] == "static_review_failed"
    assert "static_review_failed" in event_types
    assert "fix_sanitized" in event_types
    assert "fix_completed" in event_types
    assert "run_failed" in event_types
    assert "pipeline_failed" not in event_types
    assert "executor_started" not in event_types
