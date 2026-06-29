import json

from studio.core.engineering_assessment import (
    ConfidenceAssessor,
    EngineeringDecisionModel,
)


def test_confidence_assessment_scores_passing_runtime_evidence():
    run = {
        "status": "completed",
        "current_stage": "tester_completed",
        "executor_output": "ok",
        "runtime_readiness": json.dumps({"manual_run_ready": True}),
    }
    events = [
        {"event_type": "static_review_completed"},
        {"event_type": "tester_completed"},
    ]
    observation = {
        "tests": {"count": 1, "files": ["tests/test_main.py"]},
        "run_metadata_files": ["RUN.md"],
    }

    confidence = ConfidenceAssessor().assess(run, events, observation)
    decision = EngineeringDecisionModel().decide(confidence, observation, run)

    assert confidence.score == 1.0
    assert "Runtime readiness passed." in confidence.reasons
    assert decision["should_continue"] is False
    assert decision["next_objective"] == "No further engineering needed."


def test_confidence_assessment_targets_failed_runtime_readiness():
    run = {
        "status": "failed",
        "current_stage": "runtime_readiness_failed",
        "executor_output": "ok",
        "runtime_readiness": json.dumps({"manual_run_ready": False}),
    }
    events = [
        {"event_type": "static_review_completed"},
        {"event_type": "tester_completed"},
        {"event_type": "runtime_readiness_failed"},
    ]
    observation = {
        "tests": {"count": 1, "files": ["tests/test_main.py"]},
        "run_metadata_files": [],
    }

    confidence = ConfidenceAssessor().assess(run, events, observation)
    decision = EngineeringDecisionModel().decide(confidence, observation, run)

    assert confidence.score <= 0.45
    assert "Runtime readiness did not pass." in confidence.reasons
    assert decision["should_continue"] is True
    assert decision["target_area"] == "runtime_readiness"
