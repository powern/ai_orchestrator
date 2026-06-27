from pathlib import Path


def test_executor_actions_doc_exists_and_mentions_json_array():
    doc = Path("docs/executor_actions.md")
    assert doc.exists()

    text = doc.read_text(encoding="utf-8")

    assert "JSON array" in text
    assert "No markdown" in text
    assert "mkdir" in text
    assert "write_file" in text
    assert "read_file" in text
    assert "run" in text
    assert "Actions are executed only inside the project workspace" in text
