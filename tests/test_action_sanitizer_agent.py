from studio.sanitizer.agent import ActionSanitizerAgent
from studio.sanitizer.result import SanitizerResult


class FakeAdapter:
    def __init__(self):
        self.last_model = None
        self.last_system_prompt = None
        self.last_user_prompt = None

    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        self.last_model = model
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        return '[{"action":"mkdir","path":"app"}]'


def test_action_sanitizer_agent_builds_prompt_and_returns_json():
    adapter = FakeAdapter()
    agent = ActionSanitizerAgent(
        adapter=adapter,
        model="qwen2.5-coder:3b",
    )

    result = agent.sanitize('{"details":"mkdir app"}')

    assert result == '[{"action":"mkdir","path":"app"}]'
    assert adapter.last_model == "qwen2.5-coder:3b"
    assert "Action Sanitizer Agent" in adapter.last_system_prompt
    assert "Executor JSON contract" in adapter.last_system_prompt
    assert "mkdir app" in adapter.last_user_prompt


def test_action_sanitizer_agent_retries_invalid_sanitized_output():
    class RetryAdapter:
        def __init__(self):
            self.calls = 0

        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            self.calls += 1

            if self.calls == 1:
                return '[{"action":"write_file","path":"app/main.py"}]'

            return '[{"action":"write_file","path":"app/main.py","content":"print(1)"}]'

    adapter = RetryAdapter()
    agent = ActionSanitizerAgent(adapter=adapter, model="qwen2.5-coder:3b")

    result = agent.sanitize_with_retry(
        "create app/main.py",
        max_attempts=2,
    )

    assert adapter.calls == 3
    assert result.actions[0]["action"] == "write_file"
    assert result.actions[0]["content"] == "print(1)"


def test_action_sanitizer_agent_process_returns_pipeline_result():
    class Adapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            return '[{"action":"mkdir","path":"app"}]'

    agent = ActionSanitizerAgent(
        adapter=Adapter(),
        model="qwen2.5-coder:3b",
    )

    result = agent.process("create app directory")

    assert result.actions == [
        {
            "action": "mkdir",
            "path": "app",
        }
    ]


def test_action_sanitizer_process_returns_sanitizer_result():
    class Adapter:
        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            return '[{"action":"mkdir","path":"app"}]'

    agent = ActionSanitizerAgent(
        adapter=Adapter(),
        model="qwen2.5-coder:3b",
    )

    result = agent.process("create app")

    assert isinstance(result, SanitizerResult)
    assert result.actions[0]["action"] == "mkdir"
    assert result.attempts == 1
    assert result.retried is False


def test_action_sanitizer_uses_repair_agent_after_validation_error():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def ask(self, model, system_prompt, user_prompt, json_mode=False):
            self.calls += 1

            if self.calls == 1:
                return '[{"action":"write_file","path":"app/main.py"}]'

            if self.calls == 2:
                assert "Action Repair Agent" in system_prompt
                assert "write_file missing fields" in user_prompt
                return '[{"action":"write_file","path":"app/main.py","content":"print(1)"}]'

            return '[{"action":"write_file","path":"app/main.py","content":"print(1)"}]'

    adapter = Adapter()
    agent = ActionSanitizerAgent(adapter=adapter, model="qwen2.5-coder:3b")

    result = agent.process("create app/main.py", max_attempts=2)

    assert adapter.calls >= 2
    assert result.actions[0]["content"] == "print(1)"
    assert result.retried is True
