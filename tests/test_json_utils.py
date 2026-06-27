from studio.core.json_utils import strip_markdown_code_fence, normalize_coder_json, normalize_coder_json_result


def test_strip_markdown_code_fence():
    text = """```json
[
  {
    "action": "mkdir",
    "path": "app"
  }
]
```"""

    cleaned = strip_markdown_code_fence(text)

    assert cleaned.startswith("[")
    assert cleaned.endswith("]")


def test_normalize_coder_json_returns_list():
    text = """```json
[
  {
    "action": "mkdir",
    "path": "app"
  }
]
```"""

    actions = normalize_coder_json(text)

    assert actions[0]["action"] == "mkdir"
    assert actions[0]["path"] == "app"


def test_normalize_coder_json_accepts_type_and_removes_id():
    text = """```json
[
  {
    "id": 1,
    "type": "mkdir",
    "path": "app"
  }
]
```"""

    actions = normalize_coder_json(text)

    assert actions[0] == {
        "action": "mkdir",
        "path": "app",
    }


def test_normalize_coder_json_accepts_python_style_triple_quotes():
    text = '''```json
[
    {
        "id": 4,
        "type": "write_file",
        "path": "tests/test_main.py",
        "content": """
import unittest

class TestMain(unittest.TestCase):
    pass
"""
    }
]
```'''

    actions = normalize_coder_json(text)

    assert actions[0]["action"] == "write_file"
    assert actions[0]["path"] == "tests/test_main.py"
    assert "class TestMain" in actions[0]["content"]


def test_normalize_coder_json_accepts_directory_path_and_file_path():
    text = """```json
[
  {
    "action": "mkdir",
    "directory_path": "app"
  },
  {
    "action": "write_file",
    "file_path": "app/main.py",
    "content": "print('hello')"
  }
]
```"""

    actions = normalize_coder_json(text)

    assert actions[0]["path"] == "app"
    assert actions[1]["path"] == "app/main.py"


def test_normalize_coder_json_result_returns_pipeline_result():
    text = """[
      {
        "action": "mkdir",
        "path": "app"
      }
    ]"""

    result = normalize_coder_json_result(text)

    assert result.actions[0]["action"] == "mkdir"
    assert result.attempts == 1
    assert result.retried is False
