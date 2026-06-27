from studio.core.llm_adapter import LLMAdapter


class FakeOllamaClient:
    def generate(self, model, prompt):
        return "hello"


def test_llm_returns_text():
    adapter = LLMAdapter()
    adapter.client = FakeOllamaClient()

    response = adapter.ask(
        model="qwen2.5-coder:1.5b",
        system_prompt="You are a helpful assistant.",
        user_prompt="Reply with exactly: hello",
    )

    assert response == "hello"
