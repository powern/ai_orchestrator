from pathlib import Path

from studio.core.failure_analysis import FailureAnalyzer
from studio.core.repair_plan import RepairPlanner
from studio.core.tester_result import StageTestResult


def write_file(root: Path, relative_path: str, content: str = "") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_analyzer_identifies_main_as_root_cause_for_bad_package_import(tmp_path):
    write_file(
        tmp_path,
        "tests/test_calculator.py",
        "from app.main import main\n",
    )
    write_file(
        tmp_path,
        "app/main.py",
        "from application.calculator import Calculator\n",
    )
    write_file(
        tmp_path,
        "app/application/calculator.py",
        "class Calculator:\n    pass\n",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 1, in <module>\n'
            "    from app.main import main\n"
            f'  File "{tmp_path / "app" / "main.py"}", line 1, in <module>\n'
            "    from application.calculator import Calculator\n"
            "ModuleNotFoundError: No module named 'application'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.root_cause == "app/main.py"
    assert analysis.reason == "Invalid package import for missing module 'application'."
    assert plan.primary_target == "app/main.py"
    assert "app/main.py" in plan.repair_targets
    assert "tests/test_calculator.py" in plan.secondary_targets


def test_analyzer_identifies_nested_import_origin(tmp_path):
    write_file(tmp_path, "tests/test_calculator.py", "from app.main import main\n")
    write_file(tmp_path, "app/main.py", "from app.application.calculator import Calculator\n")
    write_file(
        tmp_path,
        "app/application/calculator.py",
        "from domain.temperature import Temperature\n",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 1, in <module>\n'
            "    from app.main import main\n"
            f'  File "{tmp_path / "app" / "main.py"}", line 1, in <module>\n'
            "    from app.application.calculator import Calculator\n"
            f'  File "{tmp_path / "app" / "application" / "calculator.py"}", '
            "line 1, in <module>\n"
            "    from domain.temperature import Temperature\n"
            "ModuleNotFoundError: No module named 'domain'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    assert analysis.root_cause == "app/application/calculator.py"
    assert "app/application/calculator.py" in analysis.affected_files


def test_analyzer_points_to_imported_source_file_for_syntax_error(tmp_path):
    write_file(tmp_path, "tests/test_calculator.py", "from app.application.calculator import add\n")
    write_file(tmp_path, "app/application/calculator.py", "def add(a, b):\n    return a +\n")

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 1, in <module>\n'
            "    from app.application.calculator import add\n"
            f'  File "{tmp_path / "app" / "application" / "calculator.py"}", line 2\n'
            "    return a +\n"
            "SyntaxError: invalid syntax\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    assert analysis.exception_type == "SyntaxError"
    assert analysis.root_cause == "app/application/calculator.py"


def test_analyzer_identifies_missing_dependency_file(tmp_path):
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
    plan = RepairPlanner().plan(analysis)

    assert analysis.root_cause == "app/main.py"
    assert "app/missing_service.py" in analysis.affected_files
    assert "Missing dependency file" in analysis.reason
    assert plan.primary_target == "app/main.py"
    assert "app/main.py" in plan.repair_targets
