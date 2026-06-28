import json

from studio.core.executor_schema import validate_executor_actions
from studio.sanitizer.agent import ActionSanitizerAgent


class FailIfCalledAdapter:
    def ask(self, model, system_prompt, user_prompt, json_mode=False):
        raise AssertionError("deterministic normalizer should handle this output")


def sanitize(raw_output):
    result = ActionSanitizerAgent(
        adapter=FailIfCalledAdapter(),
        model="qwen2.5-coder:3b",
    ).process(raw_output)
    validate_executor_actions(result.actions)
    return result.actions


def test_normalizer_converts_triple_quoted_content():
    raw_output = '''
[
  {
    "action": "write_file",
    "path": "app/app.py",
    "content": """
from flask import Flask

app = Flask(__name__)
"""
  }
]
'''

    actions = sanitize(raw_output)

    assert actions[0]["action"] == "write_file"
    assert actions[0]["path"] == "app/app.py"
    assert "from flask import Flask" in actions[0]["content"]
    assert "app = Flask(__name__)" in actions[0]["content"]


def test_normalizer_converts_shorthand_mkdir():
    assert sanitize('[{"mkdir": "app"}]') == [{"action": "mkdir", "path": "app"}]


def test_normalizer_converts_shorthand_run():
    assert sanitize('[{"run": "pytest tests/"}]') == [
        {"action": "run", "command": "pytest tests/"}
    ]


def test_normalizer_converts_shorthand_write_file_with_file_path():
    actions = sanitize(
        json.dumps(
            [
                {
                    "write_file": {
                        "file_path": "app/app.py",
                        "content": "print('hello')",
                    }
                }
            ]
        )
    )

    assert actions == [
        {
            "action": "write_file",
            "path": "app/app.py",
            "content": "print('hello')",
        }
    ]


def test_normalizer_handles_run_15_style_coder_output_without_retry():
    raw_output = """```json
[
  {
    "mkdir": "app"
  },
  {
    "write_file": {
      "file_path": "app/__init__.py",
      "content": ""
    }
  },
  {
    "write_file": {
      "file_path": "app/app.py",
      "content": \"\"\"
from flask import Flask, render_template_string

app = Flask(__name__)

@app.route('/')
def home_route():
    return render_template_string('''
        <h1>Counter: {{ counter }}</h1>
        <a href="/increase">Increase</a> |
        <a href="/reset">Reset</a>
    ''', counter=0)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
\"\"\"
    }
  },
  {
    "run": "pytest tests/"
  }
]
```"""

    actions = sanitize(raw_output)

    assert actions[0] == {"action": "mkdir", "path": "app"}
    assert actions[1] == {"action": "write_file", "path": "app/__init__.py", "content": ""}
    assert actions[2]["action"] == "write_file"
    assert actions[2]["path"] == "app/app.py"
    assert "render_template_string" in actions[2]["content"]
    assert "Counter: {{ counter }}" in actions[2]["content"]
    assert actions[3] == {"action": "run", "command": "pytest tests/"}


def test_normalizer_handles_fix_output_with_triple_quotes_and_shorthand():
    raw_output = '''
[
  {
    "write_file": {
      "file_path": "app/main.py",
      "content": """
def main():
    return "fixed"
"""
    }
  }
]
'''

    actions = sanitize(raw_output)

    assert actions == [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": '\ndef main():\n    return "fixed"\n',
        }
    ]
