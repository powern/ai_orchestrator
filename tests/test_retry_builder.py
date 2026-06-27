from studio.coder.retry import RetryPromptBuilder


def test_retry_builder_mentions_previous_output():
    builder = RetryPromptBuilder()

    prompt = builder.build(
        original_output='[{"action":"run_command"}]',
        error=ValueError("Unsupported action: run_command"),
    )

    assert "run_command" in prompt
    assert "Unsupported action: run_command" in prompt
    assert "Return corrected JSON now." in prompt


def test_retry_builder_lists_supported_actions():
    builder = RetryPromptBuilder()

    prompt = builder.build(
        original_output="[]",
        error=ValueError("dummy"),
    )

    for action in (
        "mkdir",
        "write_file",
        "read_file",
        "run",
    ):
        assert f"- {action}" in prompt
