import json
from pathlib import Path

from studio.contracts.execution import (
    CommandContract,
    ModuleStrategy,
    ProjectExecutionContract,
)
from studio.core.diagnostics import (
    DiagnosticCaseBuilder,
    HypothesisGenerator,
    HypothesisVerifier,
)
from studio.core.failure_analysis import FailureAnalyzer
from studio.core.repair_plan import RepairPlanner
from studio.core.tester_result import StageTestResult


def write_file(root: Path, relative_path: str, content: str = "") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def module_callable_workspace(tmp_path):
    write_file(tmp_path, "app/__init__.py", "from . import main\n")
    write_file(tmp_path, "app/main.py", "VALUE = 'not callable export'\n")
    write_file(
        tmp_path,
        "tests/test_app.py",
        "from app import main\n\n"
        "def test_main():\n"
        "    assert main() == 'ok'\n",
    )
    return StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_app.py::test_main",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_app.py"}", line 4, in test_main\n'
            "    assert main() == 'ok'\n"
            "TypeError: 'module' object is not callable\n"
        ),
    )


def test_diagnostic_case_creation_from_tester_output(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    case = analysis.diagnostic_case

    assert case["failing_test_file"] == "tests/test_app.py"
    assert analysis.exception_type == "TypeError"
    assert "tests/test_app.py" in analysis.evidence_pack["relevant_files"]


def test_evidence_pack_includes_traceback_contract_graph_and_tree(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        test_roots=["tests"],
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
    ).to_dict()

    analysis = FailureAnalyzer().analyze(
        tmp_path,
        tester_result,
        execution_contract=contract,
    )
    evidence = analysis.evidence_pack

    assert "TypeError" in evidence["traceback"]
    assert evidence["execution_contract"]["language"] == "python"
    assert "project" in evidence["project_graph"]
    assert "app/main.py" in evidence["workspace_tree"]


def test_hypothesis_generation_for_module_object_not_callable(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    hypothesis_ids = {hypothesis["hypothesis_id"] for hypothesis in analysis.hypotheses}

    assert "production-export-mismatch" in hypothesis_ids
    assert "test-calls-module" in hypothesis_ids


def test_hypothesis_verification_rejects_blindly_blaming_test_file(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    diagnosis = analysis.verified_diagnosis

    assert diagnosis["accepted_hypothesis"]["hypothesis_id"] == "production-export-mismatch"
    assert any(
        item["hypothesis_id"] == "test-calls-module"
        for item in diagnosis["rejected_hypotheses"]
    )
    assert diagnosis["symptom_location"] == "tests/test_app.py"


def test_verified_diagnosis_identifies_import_export_contract_mismatch(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    assert analysis.failure_class == "ImportOrModuleResolutionFailure"
    assert "Import/export contract mismatch" in analysis.root_cause
    assert analysis.primary_target == "app/main.py"
    assert "app/main.py" in analysis.affected_files
    assert "tests/test_app.py" in analysis.affected_files


def test_repair_planner_consumes_verified_diagnosis(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert plan.root_cause == analysis.verified_diagnosis["root_cause"]
    assert plan.primary_target == "app/main.py"


def test_repair_planner_selects_production_and_test_targets_for_mismatch(tmp_path):
    tester_result = module_callable_workspace(tmp_path)
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert "app/main.py" in plan.repair_targets
    assert "app/__init__.py" in plan.repair_targets
    assert "tests/test_app.py" in plan.secondary_targets


def test_low_confidence_diagnosis_results_in_broader_repair_targets(tmp_path):
    write_file(tmp_path, "tests/test_app.py", "def test_unknown():\n    raise RuntimeError('x')\n")
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="FAILED tests/test_app.py",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_app.py"}", line 2, in test_unknown\n'
            "RuntimeError: x\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.verified_diagnosis["confidence"] < 0.55
    assert (
        "tests/test_app.py" in plan.secondary_targets
        or "tests/test_app.py" in plan.repair_targets
    )


def test_existing_failure_analysis_behavior_remains_backward_compatible(tmp_path):
    write_file(tmp_path, "tests/test_main.py", "from app.main import main\n")
    write_file(tmp_path, "app/main.py", "from app.missing_service import MissingService\n")
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_main.py"}", line 1, in <module>\n'
            "    from app.main import main\n"
            f'  File "{tmp_path / "app" / "main.py"}", line 1, in <module>\n'
            "    from app.missing_service import MissingService\n"
            "ModuleNotFoundError: No module named 'app.missing_service'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    assert analysis.root_cause == "app/main.py"
    assert "app/missing_service.py" in analysis.affected_files
    assert analysis.verified_diagnosis


def test_api_exposes_verified_diagnosis():
    from studio.app import app
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run, save_stage_output

    init_db()
    migrate()
    project_id = create_project("Diagnostic API", "Inspect diagnosis")
    run_id = create_run(project_id)
    payload = {
        "verified_diagnosis": {
            "failure_class": "ImportOrModuleResolutionFailure",
            "accepted_hypothesis": {"hypothesis_id": "production-export-mismatch"},
            "repair_targets": ["app/main.py", "tests/test_app.py"],
            "confidence": 0.82,
        }
    }
    save_stage_output(run_id, "failure_analysis", json.dumps(payload))

    response = app.test_client().get(f"/api/runs/{run_id}")
    data = response.get_json()

    assert response.status_code == 200
    assert "production-export-mismatch" in data["stage_outputs"]["failure_analysis"]


def test_diagnostic_framework_allows_non_python_contracts(tmp_path):
    write_file(tmp_path, "NotesApp/NotesApp.csproj", "<Project />")
    tester_result = StageTestResult(False, 1, "", "NamespaceResolutionFailure: NotesApp")
    contract = ProjectExecutionContract(
        language="csharp",
        source_roots=["NotesApp"],
        build=CommandContract(required=True, command="dotnet build"),
        test=CommandContract(required=True, command="dotnet test"),
        module_strategy=ModuleStrategy(type="dotnet_namespace", namespace_root="NotesApp"),
    ).to_dict()
    case = DiagnosticCaseBuilder().build(
        tmp_path,
        tester_result,
        "NamespaceResolutionFailure",
        "NotesApp",
        [],
        {},
        execution_contract=contract,
    )
    hypotheses = HypothesisGenerator().generate(case)
    diagnosis = HypothesisVerifier().verify(case, hypotheses)

    assert case.execution_contract["language"] == "csharp"
    assert diagnosis.failure_class == "UnknownFailure"
