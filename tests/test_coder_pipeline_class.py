import pytest

from studio.coder.pipeline import CoderPipeline


def test_coder_pipeline_processes_llm_output():
    output = """```json
[
  {
    "id": 1,
    "type": "create_file",
    "file_path": "app/main.py",
    "content": "print('hello')"
  }
]
```"""

    result = CoderPipeline().process(output)

    assert result.actions == [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print('hello')",
        }
    ]


def test_coder_pipeline_rejects_invalid_action():
    output = """[
      {
        "action": "delete_everything",
        "path": "."
      }
    ]"""

    with pytest.raises(ValueError):
        CoderPipeline().process(output)


def test_pipeline_result_contains_normalized_output():
    output = """
[
  {
    "mkdir":"app"
  }
]
"""

    result = CoderPipeline().process(output)

    assert result.raw_output
    assert isinstance(result.actions, list)
