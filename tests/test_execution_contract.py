import json
from types import SimpleNamespace

from studio.contracts.execution import (
    ArtifactContract,
    CommandContract,
    ModuleStrategy,
    ProjectExecutionContract,
    infer_execution_contract,
    validate_execution_contract,
)
from studio.contracts.handoff import build_handoff
from studio.core.failure_analysis import FailureAnalyzer
from studio.core.fix_prompt import FixPromptBuilder
from studio.core.repair_plan import RepairPlanner
from studio.core.runtime_readiness import RuntimeReadinessValidator
from studio.core.tester_result import StageTestResult


def write_file(root, relative_path, content=""):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_project_execution_contract_serializes_round_trip():
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        test_roots=["tests"],
        run=CommandContract(required=True, command="python app/main.py", host="0.0.0.0", port=5000),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
        artifacts=ArtifactContract(expected_files=["requirements.txt"]),
    )

    payload = contract.to_dict()
    restored = ProjectExecutionContract.from_dict(payload)

    assert restored.to_dict() == payload
    assert json.loads(restored.to_json())["module_strategy"]["import_root"] == "app"


def test_python_contract_validation_accepts_valid_flask_layout(tmp_path):
    write_file(tmp_path, "app/__init__.py")
    write_file(
        tmp_path,
        "app/main.py",
        "from flask import Flask\napp = Flask(__name__)\n",
    )
    write_file(tmp_path, "tests/test_main.py", "from app.main import app\n")

    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        test_roots=["tests"],
        run=CommandContract(required=True, command="python app/main.py"),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
    )

    assert validate_execution_contract(contract, tmp_path) == []


def test_python_contract_validation_rejects_hyphenated_import_root(tmp_path):
    write_file(tmp_path, "personal-note-app/app/main.py", "")
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["personal-note-app"],
        test_roots=["tests"],
        run=CommandContract(required=True, command="python personal-note-app/app/main.py"),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(
            type="python_imports",
            import_root="personal-note-app.app",
        ),
    )

    violations = validate_execution_contract(contract, tmp_path)

    assert "invalid_python_import_root" in {violation.code for violation in violations}


def test_python_run_command_must_point_to_generated_file():
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        run=CommandContract(required=True, command="python app/main.py"),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
    )

    missing = validate_execution_contract(contract, planned_files=["tests/test_main.py"])
    present = validate_execution_contract(
        contract,
        planned_files=["app/main.py", "tests/test_main.py"],
    )

    assert "missing_run_command_path" in {violation.code for violation in missing}
    assert all(violation.code != "missing_run_command_path" for violation in present)


def test_csharp_contract_validation_accepts_dotnet_project(tmp_path):
    write_file(tmp_path, "NotesApp/NotesApp.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />")
    write_file(
        tmp_path,
        "NotesApp.Tests/NotesApp.Tests.csproj",
        "<Project Sdk=\"Microsoft.NET.Sdk\" />",
    )
    contract = ProjectExecutionContract(
        language="csharp",
        source_roots=["NotesApp"],
        test_roots=["NotesApp.Tests"],
        build=CommandContract(required=True, command="dotnet build"),
        run=CommandContract(required=True, command="dotnet run --project NotesApp"),
        test=CommandContract(required=True, command="dotnet test"),
        module_strategy=ModuleStrategy(type="dotnet_namespace", namespace_root="NotesApp"),
    )

    assert validate_execution_contract(contract, tmp_path) == []


def test_cpp_contract_validation_accepts_cmake_project(tmp_path):
    write_file(tmp_path, "CMakeLists.txt", "cmake_minimum_required(VERSION 3.20)\n")
    write_file(tmp_path, "src/main.cpp", "int main() { return 0; }\n")
    contract = ProjectExecutionContract(
        language="cpp",
        source_roots=["src"],
        build=CommandContract(
            required=True,
            command="cmake -S . -B build && cmake --build build",
            expected_artifacts=["build"],
        ),
        run=CommandContract(required=True, command="./build/app"),
        test=CommandContract(required=True, command="ctest --test-dir build --output-on-failure"),
        module_strategy=ModuleStrategy(type="cpp_include", include_roots=["src"]),
    )

    assert validate_execution_contract(contract, tmp_path) == []


def test_tester_uses_contract_test_command_when_available(monkeypatch, tmp_path):
    from studio.core import stages
    from studio.core.stages import run_tester_stage
    from studio.database.db import init_db
    from studio.database.migrations import migrate
    from studio.services.project_service import create_project
    from studio.services.run_service import create_run

    captured = {}

    def fake_action_run(workspace_path, command, timeout=120, working_directory="."):
        captured["command"] = command
        captured["working_directory"] = working_directory
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    contract = ProjectExecutionContract(
        language="python",
        source_roots=["src"],
        test_roots=["spec"],
        test=CommandContract(required=True, command="pytest -q spec", working_directory="pkg"),
    ).to_dict()

    context = SimpleNamespace(
        project={"workspace_path": str(tmp_path), "execution_contract": contract},
        to_dict=lambda: {
            "task": {},
            "project": {"workspace_path": str(tmp_path), "execution_contract": contract},
            "pipeline": {},
            "evidence": {},
            "validation_evidence": {},
        },
    )

    init_db()
    migrate()
    run_id = create_run(create_project("Contract Tester", ""))
    monkeypatch.setattr(stages, "build_agent_context", lambda *args, **kwargs: context)
    monkeypatch.setattr("studio.executor.actions.action_run", fake_action_run)

    result = run_tester_stage(run_id, str(tmp_path))

    assert result.success is True
    assert captured == {"command": "pytest -q spec", "working_directory": "pkg"}


def test_runtime_readiness_uses_contract_run_command(tmp_path):
    write_file(
        tmp_path,
        "app/server.py",
        "if __name__ == \"__main__\":\n    print('ready')\n",
    )
    write_file(tmp_path, "RUN.md", "Install\nRun\npython app/server.py\nTest\npytest -q\n")
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        run=CommandContract(required=True, command="python app/server.py"),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
    )

    report = RuntimeReadinessValidator().validate(tmp_path, contract)

    assert report.entrypoint_command == "python app/server.py"
    assert report.runtime_smoke == "passed"
    assert report.project_execution_contract["run"]["command"] == "python app/server.py"


def test_failure_analyzer_classifies_invalid_execution_contract(tmp_path):
    write_file(tmp_path, "personal-note-app/app/main.py", "")
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="ModuleNotFoundError: No module named 'personal-note-app.app'",
    )
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["personal-note-app"],
        module_strategy=ModuleStrategy(
            type="python_imports",
            import_root="personal-note-app.app",
        ),
    ).to_dict()

    analysis = FailureAnalyzer().analyze(
        tmp_path,
        tester_result,
        execution_contract=contract,
    )

    assert analysis.failure_class == "InvalidExecutionContract"
    assert analysis.execution_contract["module_strategy"]["import_root"] == "personal-note-app.app"


def test_repair_planner_receives_contract_information(tmp_path):
    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="ModuleNotFoundError: No module named 'bad-root.app'",
    )
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["bad-root"],
        run=CommandContract(required=True, command="python bad-root/app/main.py"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="bad-root.app"),
    ).to_dict()
    analysis = FailureAnalyzer().analyze(tmp_path, tester_result, execution_contract=contract)

    plan = RepairPlanner().plan(analysis, execution_contract=contract)

    assert plan.project_execution_contract == contract
    assert "bad-root" in plan.repair_targets


def test_fix_prompt_includes_project_execution_contract():
    tester_result = StageTestResult(False, 1, "", "ModuleNotFoundError")
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        run=CommandContract(required=True, command="python app/main.py"),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
    ).to_json()

    prompt = FixPromptBuilder().build(
        original_coder_output="[]",
        tester_result=tester_result,
        project_execution_contract=contract,
    )

    assert "Project Execution Contract:" in prompt
    assert '"run"' in prompt
    assert "Treat the Project Execution Contract as protected" in prompt


def test_decision_record_includes_execution_contract_fields():
    contract = ProjectExecutionContract(
        language="python",
        source_roots=["app"],
        test_roots=["tests"],
        run=CommandContract(required=True, command="python app/main.py"),
        test=CommandContract(required=True, command="pytest -q"),
        module_strategy=ModuleStrategy(type="python_imports", import_root="app"),
    ).to_dict()
    context = {
        "task": {},
        "project": {"execution_contract": contract, "project_graph": {}},
        "pipeline": {},
        "evidence": {},
    }

    handoff = build_handoff("architect", "coder", "Contract selected.", context)
    payload = handoff.to_dict()

    decisions = "\n".join(payload["decision_record"]["decisions"])
    assert "language: python" in decisions
    assert "run_command: python app/main.py" in decisions
    assert payload["implementation_contract"]["project_execution_contract"] == contract


def test_existing_pipeline_can_infer_contract_when_none_exists(tmp_path):
    write_file(tmp_path, "app/main.py", "def main():\n    return 'ok'\n")
    write_file(tmp_path, "tests/test_main.py", "from app.main import main\n")

    contract = infer_execution_contract(workspace_path=tmp_path)

    assert contract.language == "python"
    assert contract.test.command == "pytest -q"
