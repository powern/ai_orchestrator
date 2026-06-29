import json

from studio.contracts import PROTOCOL_SUMMARY, ProtocolValidator, build_agent_context
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project, get_project
from studio.services.run_service import create_run


def setup_database():
    init_db()
    migrate()


def test_agent_context_serializes_and_includes_original_request(tmp_path):
    setup_database()
    project_id = create_project("Protocol Context", "Create a calculator.\n- add(a, b)")
    run_id = create_run(project_id)
    context = build_agent_context(run_id, "coder")

    payload = context.to_dict()

    assert payload["task"]["original_user_request"].startswith("Create a calculator")
    assert "task" in json.loads(context.to_json())
    assert payload["project"]["project_id"] == project_id
    assert payload["project"]["run_id"] == run_id


def test_fix_agent_context_includes_original_request_and_project_graph(tmp_path):
    setup_database()
    project_id = create_project("Protocol Fix", "Create a Flask app with one page.")
    project = dict(get_project(project_id))
    run_id = create_run(project_id)
    workspace = tmp_path
    (workspace / "app").mkdir()
    (workspace / "app" / "main.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    project["workspace_path"] = str(workspace)

    context = build_agent_context(run_id, "fix", workspace_path=str(workspace))
    payload = context.to_dict()

    assert payload["task"]["original_user_request"] == "Create a Flask app with one page."
    assert payload["project"]["project_graph"]["summary"]["route_count"] == 1
    assert payload["project"]["workspace_state"]["exists"] is True


def test_protocol_validator_detects_forbidden_aliases_and_shorthand_actions():
    output = [
        {"action": "write_file", "file_path": "app/main.py", "content": "x"},
        {"action": "run", "cmd": "pytest -q"},
        {"action": "add_content", "path": "README.md", "body": "text"},
        {"mkdir": "app"},
        {"run": "pytest -q"},
    ]

    violations = ProtocolValidator().validate_agent_output(output, "coder")
    codes = [violation.code for violation in violations]

    assert codes.count("forbidden_alias") >= 3
    assert "non_canonical_action" in codes
    assert "shorthand_action" in codes


def test_protocol_validator_accepts_canonical_actions():
    output = [
        {"action": "mkdir", "path": "app"},
        {"action": "write_file", "path": "app/main.py", "content": "print('ok')\n"},
        {"action": "run", "command": "pytest -q"},
    ]

    violations = ProtocolValidator().validate_agent_output(output, "coder")

    assert violations == []


def test_protocol_violation_event_is_recorded():
    setup_database()
    from studio.core.stages import record_protocol_output

    project_id = create_project("Protocol Event", "Create app.")
    run_id = create_run(project_id)

    record_protocol_output(run_id, "coder", [{"action": "run", "cmd": "pytest -q"}])
    event_types = [event["event_type"] for event in list_events(run_id)]

    assert "agent_output_forbidden_alias" in event_types


def test_coder_prompt_includes_protocol_summary(monkeypatch):
    setup_database()
    from studio.core import stages

    class FakeAdapter:
        prompts = []

        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            self.prompts.append((system_prompt, user_prompt))
            return json.dumps(
                [
                    {"action": "mkdir", "path": "app"},
                    {
                        "action": "write_file",
                        "path": "app/main.py",
                        "content": "def main():\n    return 'ok'\n",
                    },
                ]
            )

    project_id = create_project("Coder Protocol", "Create a small Python app.")
    run_id = create_run(project_id)
    monkeypatch.setattr(stages, "LLMAdapter", FakeAdapter)

    stages.run_coder_placeholder(run_id, "planner", "architect")

    system_prompt, user_prompt = FakeAdapter.prompts[0]
    assert "Agent Protocol:" in system_prompt
    assert "file_path" in system_prompt
    assert "AgentContext:" in user_prompt
    assert "original_user_request" in user_prompt


def test_fix_prompt_includes_protocol_context():
    from studio.core.fix_prompt import FixPromptBuilder
    from studio.core.tester_result import StageTestResult

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=StageTestResult(False, 1, "failed", ""),
        task_description="Create a calculator.",
        agent_context_json='{"task": {"original_user_request": "Create a calculator."}}',
        protocol_summary=PROTOCOL_SUMMARY,
    )

    assert "Agent Protocol:" in prompt
    assert "AgentContext:" in prompt
    assert "original_user_request" in prompt
    assert "file_path" in prompt
