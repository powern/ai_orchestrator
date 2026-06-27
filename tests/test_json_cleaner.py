from studio.sanitizer.json_cleaner import clean_json_text


def test_clean_json_text_removes_json_fence():
    raw = """```json
[{"action":"mkdir","path":"app"}]
```"""

    assert clean_json_text(raw) == '[{"action":"mkdir","path":"app"}]'


def test_clean_json_text_leaves_plain_json():
    raw = '[{"action":"mkdir","path":"app"}]'

    assert clean_json_text(raw) == raw
