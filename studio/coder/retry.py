SUPPORTED_ACTIONS = [
    "mkdir",
    "write_file",
    "read_file",
    "run",
]


class RetryPromptBuilder:

    def build(self, original_output: str, error: Exception) -> str:
        actions = "\n".join(f"- {action}" for action in SUPPORTED_ACTIONS)

        return f"""
Your previous response was not valid Executor JSON.

Validation error:
{error}

Supported actions:
{actions}

Rules:
- Return ONLY valid JSON.
- Root must be a JSON array.
- Do not use markdown.
- Do not explain anything.
- Use "action", not "type".
- Use "path" for mkdir/write_file/read_file.
- Use "command" for run.
- Do not include id fields.

Previous response:
{original_output}

Return corrected JSON now.
""".strip()
