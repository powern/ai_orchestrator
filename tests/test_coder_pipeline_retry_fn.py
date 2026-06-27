from studio.coder.pipeline import CoderPipeline


def test_pipeline_uses_retry_fn_after_validation_error():
    bad_output = """[
      {
        "action": "bad_action",
        "path": "app"
      }
    ]"""

    fixed_output = """[
      {
        "action": "mkdir",
        "path": "app"
      }
    ]"""

    calls = []

    def retry_fn(original_output, error):
        calls.append((original_output, str(error)))
        return fixed_output

    result = CoderPipeline().process(
        bad_output,
        max_attempts=2,
        retry_fn=retry_fn,
    )

    assert result.actions == [
        {
            "action": "mkdir",
            "path": "app",
        }
    ]

    assert result.attempts == 2
    assert result.retried is True
    assert len(calls) == 1
    assert "Unsupported action: bad_action" in calls[0][1]
