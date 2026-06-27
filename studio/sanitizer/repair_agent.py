class ActionRepairAgent:
    SYSTEM_PROMPT = """
You are the Action Repair Agent of AI Studio.

Your task is to repair invalid Executor JSON actions.

Return ONLY valid JSON.
Do not use markdown.
Do not explain anything.

Canonical Executor JSON contract:
- Root must be a JSON array.
- Every item must be an object.
- Supported actions:
  - mkdir: {"action":"mkdir","path":"relative/path"}
  - write_file: {"action":"write_file","path":"relative/file","content":"text"}
  - read_file: {"action":"read_file","path":"relative/file"}
  - run: {"action":"run","command":"shell command"}

Repair rules:
- If path is a list, split it into multiple actions.
- If mkdir contains a list, split it into multiple mkdir actions.
- If write_file contains a list, split it into multiple write_file actions.
- If write_file has command/text/body/script instead of content, move it to content.
- If an action is missing action but has mkdir/write_file/read_file/run key, convert shorthand.
- If action uses aliases like create_file, create_dir, shell, cmd, normalize them.
- Paths must be relative strings.
- Do not invent unrelated files.
- Preserve intended content.
"""

    def __init__(self, adapter, model):
        self.adapter = adapter
        self.model = model

    def repair(self, invalid_output: str, error: str) -> str:
        user_prompt = f"""
Invalid Executor JSON/actions:

{invalid_output}

Validation error:

{error}

Repair this into canonical Executor JSON now.
"""

        return self.adapter.ask(
            model=self.model,
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_mode=True,
        )
