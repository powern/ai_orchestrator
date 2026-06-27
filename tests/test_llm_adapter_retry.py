from studio.core.llm_adapter import LLMAdapter


class FakeOllamaClient:
    def __init__(self):
        self.last_model = None
        self.last_prompt = None

    def generate(self, model, prompt):
        self.last_model = model
        self.last_prompt = prompt
        return '[{"action":"mkdir","path":"app"}]'


def test_llm_adapter_ask_retry_builds_repair_prompt():
    adapter = LLMAdapter()
    adapter.client = FakeOllamaClient()

    response = adapter.ask_retry(
        model="qwen2.5-coder:3b",
        original_output='[{"action":"bad"}]',
        error=ValueError("Unsupported action: bad"),
    )

    assert response == '[{"action":"mkdir","path":"app"}]'
    assert adapter.client.last_model == "qwen2.5-coder:3b"
    assert "Unsupported action: bad" in adapter.client.last_prompt
    assert "Return corrected JSON now." in adapter.client.last_prompt
