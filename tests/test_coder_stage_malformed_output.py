import pytest

from studio.core import stages
from studio.core.stages import run_coder_placeholder
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.event_service import list_events
from studio.services.project_service import create_project
from studio.services.run_service import create_run, get_run

VALID_ACTIONS = '[{"action":"mkdir","path":"app"}]'


class RetryThenSuccessAdapter:
    def __init__(self, initial_raw_output):
        self.initial_raw_output = initial_raw_output
        self.coder_calls = 0
        self.retry_prompts = []
        self.retry_returned = False

    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        if "You are the Coder Agent" in system_prompt:
            self.coder_calls += 1
            if "Your previous response could not be parsed." in user_prompt:
                self.retry_prompts.append(user_prompt)
                self.retry_returned = True
                return VALID_ACTIONS
            return self.initial_raw_output

        if self.retry_returned:
            return VALID_ACTIONS

        return self.initial_raw_output


class AlwaysInvalidAdapter:
    def __init__(self):
        self.retry_prompts = []

    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        if (
            "You are the Coder Agent" in system_prompt
            and "Your previous response could not be parsed." in user_prompt
        ):
            self.retry_prompts.append(user_prompt)

        return '[{"action":"write_file","path":"app/main.py","content":"unterminated}'


def create_run_for_coder_stage(description="Build a small app"):
    init_db()
    migrate()
    project_id = create_project("Malformed Coder Output", description)
    return create_run(project_id)


@pytest.mark.parametrize(
    "raw_output",
    [
        '{"action":"mkdir","path":"app"}',
        '[{"action":"write_file","path":"app/main.py","content":"127.0.0',
        '```json\n[{"action":"mkdir","path":"app"}]\n```\nextra text',
        '[{"action":"mkdir","path":"app"}]\n\nFiles:\n- app/__init__.py',
    ],
)
def test_coder_stage_retries_malformed_output_then_succeeds(monkeypatch, raw_output):
    adapter = RetryThenSuccessAdapter(raw_output)
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)

    run_id = create_run_for_coder_stage()

    output = run_coder_placeholder(run_id, "planner", "architect")

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert output == '[\n  {\n    "action": "mkdir",\n    "path": "app"\n  }\n]'
    assert run["coder_raw_output"] == raw_output
    assert run["coder_output"] == output
    assert "coder_retry" in event_types
    assert "coder_failed" not in event_types
    assert "run_failed" not in event_types
    assert adapter.retry_prompts
    assert "Previous parser error:" in adapter.retry_prompts[0]
    assert raw_output in adapter.retry_prompts[0]


def test_coder_stage_fails_cleanly_after_three_invalid_retries(monkeypatch):
    adapter = AlwaysInvalidAdapter()
    monkeypatch.setattr(stages, "LLMAdapter", lambda: adapter)

    run_id = create_run_for_coder_stage()

    output = run_coder_placeholder(run_id, "planner", "architect")

    run = get_run(run_id)
    events = list_events(run_id)
    event_types = [event["event_type"] for event in events]

    assert output is None
    assert run["status"] == "failed"
    assert run["current_stage"] == "coder_failed"
    assert run["coder_raw_output"]
    assert run["coder_output"] is None
    assert run["coder_sanitizer_error"]
    assert event_types.count("coder_retry") == 3
    assert "coder_failed" in event_types
    assert "run_failed" in event_types
    assert "pipeline_failed" not in event_types
    assert len(adapter.retry_prompts) == 3
