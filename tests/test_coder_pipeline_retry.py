import pytest

from studio.coder.pipeline import CoderPipeline


def test_pipeline_returns_pipeline_result():
    output = """[
        {
            "action":"mkdir",
            "path":"app"
        }
    ]"""

    result = CoderPipeline().process(output)

    assert result.actions[0]["action"] == "mkdir"
    assert result.attempts == 1
    assert result.retried is False


def test_pipeline_still_fails_after_max_attempts():
    output = """[
        {
            "action":"delete_everything"
        }
    ]"""

    with pytest.raises(ValueError):
        CoderPipeline().process(output, max_attempts=2)
