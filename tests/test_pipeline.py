from studio.core.pipeline import get_pipeline_stages, FINAL_STAGE, FAILED_STAGE


def test_pipeline_stages_order():
    assert get_pipeline_stages() == [
        "planner",
        "architect",
        "coder",
        "executor",
        "tester",
    ]


def test_pipeline_final_and_failed_stage_names():
    assert FINAL_STAGE == "completed"
    assert FAILED_STAGE == "failed"
