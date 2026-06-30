import json
import shutil
from pathlib import Path

from studio.core import stages
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
                {
                    "schema_version": 1,
                    "project_summary": "Simple Python app with tests.",
                    "tests": {"command": "pytest -q"},
                    "steps": [
                        {
                            "type": "create_directory",
                            "path": "app",
                            "purpose": "Application package",
                            "content_description": "Package directory",
                        },
                        {
                            "type": "create_directory",
                            "path": "tests",
                            "purpose": "Test package",
                            "content_description": "Test directory",
                        },
                        {
                            "type": "create_file",
                            "path": "app/__init__.py",
                            "purpose": "Package marker",
                            "content_description": "Empty package marker",
                            "content": "",
                        },
                        {
                            "type": "create_file",
                            "path": "app/main.py",
                            "purpose": "Flask application entry point",
                            "content_description": "Visual smoke counter app",
                            "content": (
                                "from flask import Flask, redirect, "
                                "render_template_string, url_for\n\n"
                                "app = Flask(__name__)\n\n\n"
                                "counter = {'value': 0}\n\n\n"
                                "TEMPLATE = '''<h1>Visual Smoke Test</h1>"
                                "<p>Counter: {{ value }}</p>"
                                "<a href=\"/increase\">Increase</a>"
                                "<a href=\"/reset\">Reset</a>'''\n\n\n"
                                "@app.route('/')\n"
                                "def index():\n"
                                "    return render_template_string(TEMPLATE, "
                                "value=counter['value'])\n\n\n"
                                "@app.route('/increase')\n"
                                "def increase():\n"
                                "    counter['value'] += 1\n"
                                "    return redirect(url_for('index'))\n\n\n"
                                "@app.route('/reset')\n"
                                "def reset():\n"
                                "    counter['value'] = 0\n"
                                "    return redirect(url_for('index'))\n\n\n"
                                "if __name__ == \"__main__\":\n"
                                "    app.run(host=\"0.0.0.0\", port=5000)\n"
                            ),
                        },
                        {
                            "type": "create_file",
                            "path": "tests/test_main.py",
                            "purpose": "Behavior test",
                            "content_description": "Validate visible counter behavior",
                            "content": (
                                "from app.main import app, counter\n\n\n"
                                "def test_counter_visible_behavior():\n"
                                "    counter['value'] = 0\n"
                                "    client = app.test_client()\n"
                                "    response = client.get('/')\n"
                                "    assert response.status_code == 200\n"
                                "    assert b'Visual Smoke Test' in response.data\n"
                                "    assert b'Counter: 0' in response.data\n"
                                "    assert b'Increase' in response.data\n"
                                "    assert b'Reset' in response.data\n"
                                "    response = client.get('/increase', follow_redirects=True)\n"
                                "    assert b'Counter: 1' in response.data\n"
                                "    response = client.get('/reset', follow_redirects=True)\n"
                                "    assert b'Counter: 0' in response.data\n"
                            ),
                        },
                        {
                            "type": "create_file",
                            "path": "requirements.txt",
                            "purpose": "Python dependencies",
                            "content_description": "Compatible Flask runtime dependencies",
                            "content": "Flask==3.0.0\nWerkzeug==3.0.1\n",
                        },
                        {
                            "type": "create_file",
                            "path": "RUN.md",
                            "purpose": "Manual run metadata",
                            "content_description": "Install, run, and test commands",
                            "content": (
                                "Install:\n"
                                "No external dependencies.\n\n"
                                "Run:\n"
                                "python app/main.py\n\n"
                                "Open:\n"
                                "http://127.0.0.1:5000/\n\n"
                                "Test:\n"
                                "pytest -q\n"
                            ),
                        },
                    ]
                }
            )
        return "1. Create Flask app\n2. Add one page\n3. Add tests"


class MalformedCoderLLMAdapter:
    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        if not json_mode:
            return "Files:\n- app/main.py\n- tests/test_main.py"

        return '{"schema_version":1,"steps":[{"type":"create_file","path":"app/main.py"'


def test_scheduler_processes_next_queued_run(monkeypatch):
    init_db()
    migrate()

    monkeypatch.setattr(worker, "LLMAdapter", lambda: FakeLLMAdapter())
    monkeypatch.setattr(stages, "LLMAdapter", FakeLLMAdapter)

    project_id = create_project(
        "Scheduler Planner Test Project",
        "Create a simple Flask app with one page.",
    )
    workspace = Path(get_project(project_id)["workspace_path"])
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)

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


def test_scheduler_keeps_malformed_coder_output_inside_coder_stage(monkeypatch):
    init_db()
    migrate()

    monkeypatch.setattr(worker, "LLMAdapter", lambda: FakeLLMAdapter())
    monkeypatch.setattr(stages, "LLMAdapter", MalformedCoderLLMAdapter)

    project_id = create_project(
        "Self Healing GUI Test 2",
        "Generate a larger project that may produce malformed coder output.",
    )
    workspace = Path(get_project(project_id)["workspace_path"])
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
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
