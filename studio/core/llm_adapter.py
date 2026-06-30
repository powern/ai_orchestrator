import json

from core.ollama_client import OllamaClient


class LLMAdapter:

    def __init__(self):
        self.client = OllamaClient()

    def ask(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:

        prompt = f"""SYSTEM

{system_prompt}

USER

{user_prompt}
"""

        if json_mode:
            prompt += """

Return ONLY valid JSON.
Do not use markdown.
Do not explain anything.
"""

        return self.client.generate(
            model=model,
            prompt=prompt,
        ).strip()

    def ask_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ):

        text = self.ask(
            model,
            system_prompt,
            user_prompt,
            json_mode=True,
        )

        return json.loads(text)
