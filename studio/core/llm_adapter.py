import json
from typing import Optional

from core.ollama_client import OllamaClient
from studio.coder.retry import RetryPromptBuilder


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


    def ask_retry(self, model, original_output, error):
        retry_prompt = RetryPromptBuilder().build(
            original_output=original_output,
            error=error,
        )

        return self.ask(
            model=model,
            system_prompt="You repair invalid Executor JSON.",
            user_prompt=retry_prompt,
            json_mode=True,
        )
