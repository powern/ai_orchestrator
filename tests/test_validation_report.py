import json

from studio.app import app
from studio.core.engineering_assessment import ConfidenceAssessor, EngineeringDecisionModel
from studio.core.failure_analysis import FailureAnalysis
from studio.core.fix_prompt import FixPromptBuilder
from studio.core.project_state import ProjectStateBuilder
from studio.core.repair_plan import RepairPlanner
from studio.core.tester_result import StageTestResult
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.reviewer.static_agent import StaticReviewerAgent
from studio.services.project_service import create_project
from studio.services.run_service import create_run, save_stage_output


def test_static_reviewer_generates_structured_validation_report():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": (
                "from flask import Flask\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/increase')\n"
                "def increase():\n"
                "    return redirect(url_for('index'))\n"
            ),
        }
    ]

    result = StaticReviewerAgent().review(actions)
    report = result.validation_report

    assert result.approved is False
    assert report is not None
    assert report.approved is False
    assert report.summary["critical"] >= 3
    assert {item.id for item in report.violations} >= {
        "missing_flask_helper_import_redirect",
        "missing_flask_helper_import_url_for",
        "missing_entrypoint",
    }
    assert all(item.repair_hint for item in report.violations)


def test_validation_report_detects_source_of_truth_mismatch():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "def main():\n    return 'ok'\n",
        }
    ]
    state = ProjectStateBuilder().build(
        executor_actions=actions,
        project_specification={
            "project_type": "web_app",
            "language": "python",
            "framework": "flask",
            "runtime": {"kind": "web"},
            "features": [],
            "entities": [],
            "expected_files": ["app/main.py"],
            "acceptance_criteria": [],
            "confidence": 0.9,
            "evidence": ["test fixture"],
        },
    ).to_dict()
    state["execution_contract"]["language"] = "node"

    result = StaticReviewerAgent().review(actions, project_state=state)

    assert any(
        item.id == "source_of_truth_mismatch_language"
        for item in result.validation_report.violations
    )


def test_repair_planner_consumes_validation_report_targets():
    analysis = FailureAnalysis(
        exception_type="StaticReviewError",
        message="Static review rejected executor actions.",
        failure_class="InvalidExecutionContract",
        root_cause=None,
        primary_target=None,
        reason="static review failed",
        confidence=0.8,
        affected_files=[],
    )
    report = StaticReviewerAgent().review(
        [
            {
                "action": "write_file",
                "path": "app/main.py",
                "content": "print('Hello, World!')\n",
            }
        ]
    ).validation_report

    plan = RepairPlanner().plan(analysis, validation_report=report)

    assert "app/main.py" in plan.repair_targets
    assert plan.validation_report["violations"][0]["id"] == "placeholder_text"


def test_fix_prompt_includes_validation_report():
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="Static review rejected executor actions.",
        stderr="missing_entrypoint",
    )
    validation_report = {
        "approved": False,
        "summary": {"critical": 1, "major": 0, "minor": 0},
        "violations": [
            {
                "id": "missing_entrypoint",
                "severity": "critical",
                "category": "entrypoints",
                "message": "Flask app is missing manual app.run entrypoint in app/main.py",
                "location": "app/main.py",
                "repair_hint": "Add app.run.",
                "affected_files": ["app/main.py"],
            }
        ],
    }

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
        validation_report=json.dumps(validation_report),
    )

    assert "Validation Report:" in prompt
    assert "missing_entrypoint" in prompt
    assert "Satisfy critical Validation Report violations" in prompt


def test_engineering_assessment_targets_failed_validation_report():
    run = {
        "status": "failed",
        "current_stage": "static_review_failed",
        "executor_output": "rejected",
        "validation_report": json.dumps(
            {
                "approved": False,
                "summary": {"critical": 1, "major": 0, "minor": 0},
                "violations": [{"id": "missing_entrypoint"}],
            }
        ),
    }
    events = [{"event_type": "static_review_failed"}]
    observation = {"tests": {"count": 1}, "run_metadata_files": []}

    confidence = ConfidenceAssessor().assess(run, events, observation)
    decision = EngineeringDecisionModel().decide(confidence, observation, run)

    assert "Structured validation has unresolved findings" in "; ".join(confidence.reasons)
    assert decision["target_area"] == "validation_report"


def test_run_api_exposes_validation_report():
    init_db()
    migrate()
    project_id = create_project("Validation API", "Create Flask app.")
    run_id = create_run(project_id)
    save_stage_output(
        run_id,
        "validation_report",
        json.dumps({"approved": False, "summary": {"critical": 1}}),
    )

    response = app.test_client().get(f"/api/runs/{run_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["stage_outputs"]["validation_report"]
    assert payload["run"]["validation_report"]
