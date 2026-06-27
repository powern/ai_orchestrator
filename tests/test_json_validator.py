from studio.sanitizer.validator import JsonValidator


def test_json_validator_accepts_valid_executor_json():
    validator = JsonValidator()

    result = validator.validate('[{"action":"mkdir","path":"app"}]')

    assert result.actions[0]["action"] == "mkdir"
    assert result.actions[0]["path"] == "app"


def test_json_validator_accepts_fenced_json():
    validator = JsonValidator()

    result = validator.validate("""```json
[{"action":"mkdir","path":"app"}]
```""")

    assert result.actions[0]["action"] == "mkdir"
