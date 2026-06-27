from studio.sanitizer.result import SanitizerResult


def test_sanitizer_result_holds_actions_and_metadata():
    result = SanitizerResult(
        actions=[
            {
                "action": "mkdir",
                "path": "app",
            }
        ],
        raw_output='[{"action":"mkdir","path":"app"}]',
        attempts=1,
        retried=False,
    )

    assert result.actions[0]["action"] == "mkdir"
    assert result.raw_output.startswith("[")
    assert result.attempts == 1
    assert result.retried is False
    assert result.validation_error is None


def test_sanitizer_result_exposes_executor_program():
    result = SanitizerResult(
        actions=[
            {
                "action": "mkdir",
                "path": "app",
            }
        ],
        raw_output='[{"action":"mkdir","path":"app"}]',
        attempts=1,
        retried=False,
    )

    assert result.program.actions[0].action == "mkdir"
    assert result.program.to_dicts() == result.actions
