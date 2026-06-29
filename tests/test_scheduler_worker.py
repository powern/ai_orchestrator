import json

from studio.core import run_pipeline, stages
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.scheduler import worker
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run, get_next_queued_run, get_run
from studio.services.runtime_service import get_project_runtime


class FakeLLMAdapter:
    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        if json_mode:
            return json.dumps(
                [
                    {
                        "action": "mkdir",
                        "path": "app",
                    },
                    {
                        "action": "mkdir",
                        "path": "tests",
                    },
                    {
                        "action": "write_file",
                        "path": "app/__init__.py",
                        "content": "",
                    },
                    {
                        "action": "write_file",
                        "path": "app/main.py",
                        "content": (
                            "def main():\n"
                            "    return 'hello'\n\n\n"
                            "if __name__ == \"__main__\":\n"
                            "    print(main())\n"
                        ),
                    },
                    {
                        "action": "write_file",
                        "path": "tests/test_main.py",
                        "content": (
                            "from app.main import main\n\n"
                            "def test_main():\n"
                            "    assert main() == 'hello'\n"
                        ),
                    },
                    {
                        "action": "write_file",
                        "path": "RUN.md",
                        "content": (
                            "Install:\n"
                            "No external dependencies.\n\n"
                            "Run:\n"
                            "python app/main.py\n\n"
                            "Test:\n"
                            "pytest -q\n"
                        ),
                    },
                ]
            )
        return "1. Create Flask app\n2. Add one page\n3. Add tests"


class MalformedCoderLLMAdapter:
    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        if not json_mode:
            return "Files:\n- app/main.py\n- tests/test_main.py"

        return '[{"action":"write_file","path":"app/main.py","content":"unterminated}'


def test_scheduler_processes_next_queued_run(monkeypatch):
    init_db()
    migrate()

    monkeypatch.setattr(worker, "LLMAdapter", lambda: FakeLLMAdapter())
    monkeypatch.setattr(stages, "LLMAdapter", FakeLLMAdapter)
    monkeypatch.setattr(
        run_pipeline,
        "run_engineering_critic_stage",
        lambda *_, **__: _critic_result("approved"),
    )

    project_id = create_project(
        "Scheduler Planner Test Project",
        "Create a simple Flask app with one page.",
    )

    create_run(project_id)

    expected_run = get_next_queued_run()
    expected_run_id = expected_run["id"]
    expected_project_id = expected_run["project_id"]

    processed = worker.process_one_run()

    run = get_run(expected_run_id)
    events = list_events(expected_run_id)

    event_types = [event["event_type"] for event in events]

    assert processed is True
    assert run["status"] == "completed"
    assert run["current_stage"] == "tester_completed"
    assert get_project(expected_project_id)["status"] == "completed"
    assert get_project_runtime(expected_project_id)["status"] == "completed"
    assert run["planner_output"]
    assert run["coder_output"]
    assert "scheduler" in event_types
    assert "planner_started" in event_types
    assert "planner_completed" in event_types
    assert "architect_started" in event_types
    assert "architect_completed" in event_types
    assert "coder_started" in event_types
    assert "coder_completed" in event_types
    assert "executor_started" in event_types
    assert "tester_completed" in event_types


class _critic_result:
    def __init__(self, status):
        self.status = status

    def to_json(self):
        return json.dumps({"status": self.status})


def test_scheduler_keeps_malformed_coder_output_inside_coder_stage(monkeypatch):
    init_db()
    migrate()

    monkeypatch.setattr(worker, "LLMAdapter", lambda: FakeLLMAdapter())
    monkeypatch.setattr(stages, "LLMAdapter", MalformedCoderLLMAdapter)

    project_id = create_project(
        "Self Healing GUI Test 2",
        "Generate a larger project that may produce malformed coder output.",
    )
    create_run(project_id)

    expected_run = get_next_queued_run()
    expected_run_id = expected_run["id"]
    expected_project_id = expected_run["project_id"]

    processed = worker.process_one_run()

    run = get_run(expected_run_id)
    events = list_events(expected_run_id)
    event_types = [event["event_type"] for event in events]

    assert processed is True
    assert run["status"] == "failed"
    assert run["current_stage"] == "coder_failed"
    assert run["coder_raw_output"]
    assert run["coder_sanitizer_error"]
    assert get_project(expected_project_id)["status"] == "failed"
    assert get_project_runtime(expected_project_id)["status"] == "failed"
    assert event_types.count("coder_retry") == 3
    assert "coder_failed" in event_types
    assert "run_failed" in event_types
    assert "pipeline_failed" not in event_types
    assert "executor_started" not in event_types
    assert "tester_started" not in event_types
