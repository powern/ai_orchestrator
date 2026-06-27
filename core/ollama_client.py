import requests

from studio.config.settings import (
    DEFAULT_MODELS,
    OLLAMA_GENERATE_TIMEOUT,
    OLLAMA_NUM_PREDICT,
    OLLAMA_TEMPERATURE,
)


class OllamaClient:
    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    def list_models(self):
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            response.raise_for_status()
            models = response.json().get("models", [])
            if models:
                return models
        except requests.RequestException:
            pass

        return [{"name": model} for model in DEFAULT_MODELS.values()]

    def generate(self, model, prompt):
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": OLLAMA_NUM_PREDICT,
                    "temperature": OLLAMA_TEMPERATURE,
                },
            },
            timeout=OLLAMA_GENERATE_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("response", "")

