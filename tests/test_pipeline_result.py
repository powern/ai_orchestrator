from studio.coder.result import PipelineResult


def test_pipeline_result_defaults():
    result = PipelineResult(
        actions=[],
        raw_output="raw",
        repaired_output="repaired",
    )

    assert result.actions == []
    assert result.raw_output == "raw"
    assert result.repaired_output == "repaired"
    assert result.attempts == 1
    assert result.retried is False
    assert result.validation_error is None
