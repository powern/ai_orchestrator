CANONICAL_ACTIONS = {"mkdir", "write_file", "read_file", "run"}

FORBIDDEN_ALIASES = {
    "file_path",
    "filename",
    "cmd",
    "body",
    "add_content",
}

PROTOCOL_SUMMARY = """
Agent Protocol:
- Preserve original_user_request, non_negotiable_requirements, and acceptance_criteria.
- Coder outputs an Engineering Plan; the deterministic Action Builder outputs Executor JSON.
- Output canonical Executor JSON actions only when a stage explicitly requests actions.
- Canonical action fields are action, path, content, and command.
- Forbidden aliases: file_path, filename, cmd, body, add_content.
- Shorthand actions are forbidden: {"mkdir": "app"}, {"run": "pytest"}, {"write_file": ...}.
- The normalizer may tolerate legacy input, but agents must not emit legacy output.
- Do not replace requested functionality with placeholders or Hello World.
- Do not remove features to make validation pass.
""".strip()
