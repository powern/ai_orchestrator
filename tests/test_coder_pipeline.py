import pytest

from studio.coder.normalizer import normalize
from studio.coder.repair import repair
from studio.coder.validator import validate


def test_repair_strips_markdown_and_triple_quotes():
    raw = '''```json
[
  {
    "action": "write_file",
    "path": "app/main.py",
    "content": """
print('hello')
"""
  }
]
```'''

    repaired = repair(raw)

    assert repaired.startswith("[")
    assert "```" not in repaired
    assert '"""' not in repaired
    assert "print('hello')" in repaired


def test_normalize_action_aliases():
    actions = [
        {
            "id": 1,
            "type": "mkdir",
            "directory_path": "app",
        },
        {
            "id": 2,
            "type": "write_file",
            "file_path": "app/main.py",
            "content": "print('hello')",
        },
    ]

    normalized = normalize(actions)

    assert normalized[0] == {
        "action": "mkdir",
        "path": "app",
    }

    assert normalized[1] == {
        "action": "write_file",
        "path": "app/main.py",
        "content": "print('hello')",
    }


def test_validator_accepts_valid_actions():
    actions = [
        {
            "action": "mkdir",
            "path": "app",
        },
        {
            "action": "run",
            "command": "pytest -q",
        },
    ]

    assert validate(actions) == actions


def test_validator_rejects_missing_required_fields():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
        }
    ]

    with pytest.raises(ValueError):
        validate(actions)


def test_validator_rejects_unknown_action():
    actions = [
        {
            "action": "delete_everything",
            "path": ".",
        }
    ]

    with pytest.raises(ValueError):
        validate(actions)


def test_normalize_create_file_alias():
    actions = [
        {
            "action": "create_file",
            "file_path": "app/main.py",
            "content": "print('hello')",
        }
    ]

    normalized = normalize(actions)

    assert normalized[0] == {
        "action": "write_file",
        "path": "app/main.py",
        "content": "print('hello')",
    }


def test_normalize_run_command_alias():
    actions = [
        {
            "action": "run_command",
            "cmd": "pytest -q",
        }
    ]

    normalized = normalize(actions)

    assert normalized[0] == {
        "action": "run",
        "command": "pytest -q",
    }


def test_normalize_append_content_alias():
    actions = [
        {
            "action": "append_content",
            "file_path": "README.md",
            "content": "hello",
        }
    ]

    normalized = normalize(actions)

    assert normalized[0] == {
        "action": "write_file",
        "path": "README.md",
        "content": "hello",
    }


def test_normalize_shorthand_actions():
    actions = [
        {"mkdir": "app"},
        {"write_file": {"path": "app/main.py", "content": "print('hello')"}},
        {"run": "pytest tests"},
    ]

    normalized = normalize(actions)

    assert normalized[0] == {
        "action": "mkdir",
        "path": "app",
    }

    assert normalized[1] == {
        "action": "write_file",
        "path": "app/main.py",
        "content": "print('hello')",
    }

    assert normalized[2] == {
        "action": "run",
        "command": "pytest tests",
    }


def test_normalize_batch_actions():
    actions = [
        {"mkdir": ["app", "tests"]},
        {
            "write_file": [
                {"path": "app/main.py", "content": "print('hello')"},
                {"path": "tests/test_main.py", "content": "def test_ok(): pass"},
            ]
        },
        {"run": ["pytest"]},
    ]

    normalized = normalize(actions)

    assert normalized == [
        {
            "action": "mkdir",
            "path": "app",
        },
        {
            "action": "mkdir",
            "path": "tests",
        },
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print('hello')",
        },
        {
            "action": "write_file",
            "path": "tests/test_main.py",
            "content": "def test_ok(): pass",
        },
        {
            "action": "run",
            "command": "pytest",
        },
    ]


def test_normalize_write_file_command_as_content():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "command": "def main(): pass",
        }
    ]

    normalized = normalize(actions)

    assert normalized[0] == {
        "action": "write_file",
        "path": "app/main.py",
        "content": "def main(): pass",
    }


def test_normalize_action_with_path_list_expands_to_multiple_actions():
    actions = [
        {
            "action": "mkdir",
            "path": ["app", "tests"],
        }
    ]

    normalized = normalize(actions)

    assert normalized == [
        {
            "action": "mkdir",
            "path": "app",
        },
        {
            "action": "mkdir",
            "path": "tests",
        },
    ]
