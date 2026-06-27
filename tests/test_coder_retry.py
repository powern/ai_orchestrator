from studio.coder.retry import RetryPromptBuilder


def test_retry_prompt_contains_error_and_supported_actions():
    prompt = RetryPromptBuilder().build(
        original_output='[{"action":"bad"}]',
        error=ValueError("Unsupported action: bad"),
    )

    assert "Unsupported action: bad" in prompt
    assert "Supported actions:" in prompt
    assert "- mkdir" in prompt
    assert "- write_file" in prompt
    assert "- read_file" in prompt
    assert "- run" in prompt
    assert "Return ONLY valid JSON" in prompt
    assert "Previous response:" in prompt
