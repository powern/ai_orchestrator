# Executor Actions

Executor output is a JSON array of action objects. The orchestrator normalizes
LLM output into an `ExecutorProgram` AST before execution, then executes each
`ExecutorAction` in order.

No markdown, prose, or comments should be included in LLM executor output.

Supported actions:

- `mkdir`: requires `path`
- `write_file`: requires `path` and `content`
- `read_file`: requires `path`
- `run`: requires `command`, with optional `timeout`

Paths must be relative to the project workspace. Absolute paths and path
traversal are rejected.
Actions are executed only inside the project workspace.

Allowed commands are intentionally narrow:

- `pytest`
- `python -m pytest`

Example:

```json
[
  {
    "action": "mkdir",
    "path": "app"
  },
  {
    "action": "write_file",
    "path": "app/main.py",
    "content": "def main():\n    return 'hello'\n"
  },
  {
    "action": "run",
    "command": "pytest -q"
  }
]
```
