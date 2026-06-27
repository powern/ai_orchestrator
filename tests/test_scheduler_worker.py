from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.project_service import create_project
from studio.services.run_service import create_run, get_next_queued_run, get_run
from studio.services.event_service import list_events
from studio.scheduler import worker
from studio.core import stages


class FakeLLMAdapter:
    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        if json_mode:
            return """
            [
              {
                "action": "mkdir",
                "path": "app"
              },
              {
                "action": "mkdir",
                "path": "tests"
              },
              {
                "action": "write_file",
                "path": "app/__init__.py",
                "content": ""
              },
              {
                "action": "write_file",
                "path": "app/main.py",
                "content": "def main():\\n    return 'hello'\\n"
              },
              {
                "action": "write_file",
                "path": "tests/test_main.py",
                "content": "from app.main import main\\n\\ndef test_main():\\n    assert main() == 'hello'\\n"
              }
            ]
            """
        return "1. Create Flask app\n2. Add one page\n3. Add tests"


def test_scheduler_processes_next_queued_run(monkeypatch):
    init_db()
    migrate()

    monkeypatch.setattr(worker, "LLMAdapter", lambda: FakeLLMAdapter())
    monkeypatch.setattr(stages, "LLMAdapter", FakeLLMAdapter)

    project_id = create_project(
        "Scheduler Planner Test Project",
        "Create a simple Flask app with one page.",
    )

    create_run(project_id)

    expected_run = get_next_queued_run()
    expected_run_id = expected_run["id"]

    processed = worker.process_one_run()

    run = get_run(expected_run_id)
    events = list_events(expected_run_id)

    event_types = [event["event_type"] for event in events]

    assert processed is True
    assert run["status"] == "completed"
    assert run["current_stage"] == "tester_completed"
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
