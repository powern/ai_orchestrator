from studio.core.pipeline_engine import PipelineEngine


def test_pipeline_engine_returns_pipeline():
    engine = PipelineEngine()

    assert engine.list_stages() == [
        "planner",
        "architect",
        "coder",
        "executor",
        "tester",
    ]
