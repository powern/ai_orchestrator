from core.ollama_client import OllamaClient


def test_ollama_models_available():
    client = OllamaClient()
    models = client.list_models()

    model_names = [m["name"] for m in models]

    assert "qwen2.5:7b" in model_names
    assert "qwen2.5-coder:3b" in model_names
