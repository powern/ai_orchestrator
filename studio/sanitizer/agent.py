from studio.core.agent import BaseAgent
from studio.sanitizer.repair_agent import ActionRepairAgent
from studio.sanitizer.result import SanitizerResult
from studio.sanitizer.validator import JsonValidator


class ActionSanitizerAgent(BaseAgent):
    name = "sanitizer"

    SYSTEM_PROMPT = """
You are the Action Sanitizer Agent of AI Studio.

Your only job is to convert any Coder Agent output into valid Executor JSON.

Return ONLY valid JSON.
Do not use markdown.
Do not explain anything.

Executor JSON contract:
- Root must be a JSON array.
- Every item must be an object.
- Supported actions:
  - mkdir
  - write_file
  - read_file
  - run

Required fields:
- mkdir: action, path
- write_file: action, path, content
- read_file: action, path
- run: action, command

Rules:
- Preserve intended files and content.
- Convert shorthand formats into Executor JSON.
- Convert task/details formats into Executor JSON if possible.
- Convert command/text/body/script fields to content for write_file when needed.
- Use relative paths only.
- Do not invent extra features.
- Do not modify AI Studio itself.
"""

    def __init__(self, adapter, model):
        self.adapter = adapter
        self.model = model

    def sanitize(self, coder_output: str) -> str:
        user_prompt = f"""
Coder output:

{coder_output}

Convert this to valid Executor JSON now.
"""

        return self.adapter.ask(
            model=self.model,
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_mode=True,
        )

    def process(self, coder_output: str, max_attempts: int = 2):
        return self.sanitize_with_retry(
            coder_output=coder_output,
            max_attempts=max_attempts,
        )

    def sanitize_with_retry(self, coder_output: str, max_attempts: int = 2):
        last_error = None
        current_input = coder_output

        for attempt in range(1, max_attempts + 1):
            sanitized_output = self.sanitize(current_input)

            try:
                result = JsonValidator().validate(
                    sanitized_output,
                )

                return SanitizerResult(
                    actions=result.actions,
                    raw_output=sanitized_output,
                    attempts=attempt,
                    retried=(attempt > 1),
                    validation_error=None,
                )

            except Exception as exc:
                last_error = exc

                if attempt >= max_attempts:
                    raise

                repair_agent = ActionRepairAgent(
                    adapter=self.adapter,
                    model=self.model,
                )

                current_input = repair_agent.repair(
                    invalid_output=sanitized_output,
                    error=str(exc),
                )

        raise last_error
