from studio.sanitizer.repair_agent import ActionRepairAgent


class FakeAdapter:
    def __init__(self):
        self.last_user_prompt = None

    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        self.last_user_prompt = user_prompt
        return '[{"action":"mkdir","path":"app"},{"action":"mkdir","path":"tests"}]'


def test_action_repair_agent_builds_repair_prompt():
    adapter = FakeAdapter()
    agent = ActionRepairAgent(adapter=adapter, model="qwen2.5-coder:3b")

    result = agent.repair(
        invalid_output='[{"action":"mkdir","path":["app","tests"]}]',
        error="'list' object has no attribute 'startswith'",
    )

    assert result.startswith("[")
    assert "path" in adapter.last_user_prompt
    assert "Validation error" in adapter.last_user_prompt
