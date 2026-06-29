import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.contracts.execution import validate_execution_contract
from studio.core.diagnostics import (
    DiagnosticCaseBuilder,
    HypothesisGenerator,
    HypothesisVerifier,
)
from studio.core.fix_prompt import FixWorkspaceContextBuilder
from studio.core.tester_result import StageTestResult

IMPORT_PATTERN = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+|import\s+([\w.]+))")
FILE_PATTERN = re.compile(r'File "([^"]+\.py)"')
SHORT_FILE_PATTERN = re.compile(r"((?:app|tests)[/\\][\w./\\-]+\.py)")
EXCEPTION_PATTERN = re.compile(r"(?m)^([A-Za-z_][\w.]*Error|SyntaxError|ImportError):\s*(.*)$")
MISSING_MODULE_PATTERN = re.compile(r"No module named ['\"]([^'\"]+)['\"]")
IMPORT_NAME_PATTERN = re.compile(r"cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]")
ATTRIBUTE_MODULE_PATTERN = re.compile(
    r"module ['\"]([^'\"]+)['\"] has no attribute ['\"]([^'\"]+)['\"]"
)


@dataclass(frozen=True)
class FailureAnalysis:
    exception_type: str
    message: str
    failure_class: str
    root_cause: str | None
    primary_target: str | None
    reason: str
    confidence: float
    affected_files: list[str] = field(default_factory=list)
    import_chain: list[str] = field(default_factory=list)
    missing_module: str | None = None
    workspace_tree: str = ""
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)
    execution_contract: dict[str, Any] = field(default_factory=dict)
    diagnostic_case: dict[str, Any] = field(default_factory=dict)
    evidence_pack: dict[str, Any] = field(default_factory=dict)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    verified_diagnosis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "exception_type": self.exception_type,
            "message": self.message,
            "failure_class": self.failure_class,
            "root_cause": self.root_cause,
            "primary_target": self.primary_target,
            "reason": self.reason,
            "confidence": self.confidence,
            "affected_files": self.affected_files,
            "import_chain": self.import_chain,
            "missing_module": self.missing_module,
            "workspace_tree": self.workspace_tree,
            "dependency_graph": self.dependency_graph,
            "execution_contract": self.execution_contract,
            "diagnostic_case": self.diagnostic_case,
            "evidence_pack": self.evidence_pack,
            "hypotheses": self.hypotheses,
            "verified_diagnosis": self.verified_diagnosis,
        }


class FailureAnalyzer:
    def analyze(
        self,
        workspace_path: str | Path,
        tester_result: StageTestResult,
        bug_report: str = "",
        execution_contract: dict[str, Any] | None = None,
        project_state: dict[str, Any] | None = None,
    ) -> FailureAnalysis:
        workspace = Path(workspace_path)
        output = f"{tester_result.stdout}\n{tester_result.stderr}\n{bug_report}"
        exception_type, message = self._exception(output)
        contract_violations = validate_execution_contract(execution_contract, workspace)
        failure_class = self._failure_class(
            exception_type,
            message,
            execution_contract or {},
            contract_violations,
        )
        missing_module = self._missing_module(output)
        import_error_module = self._import_error_module(message)
        attribute_module = self._attribute_error_module(message)
        traceback_files = self._traceback_files(workspace, output)
        dependency_graph = self._dependency_graph(workspace)
        diagnostic_case = DiagnosticCaseBuilder().build(
            workspace,
            tester_result,
            exception_type,
            message,
            traceback_files,
            dependency_graph,
            execution_contract=execution_contract,
            project_state=project_state,
        )
        hypotheses = HypothesisGenerator().generate(diagnostic_case)
        verified_diagnosis = HypothesisVerifier().verify(diagnostic_case, hypotheses)

        root_cause = self._root_cause(
            workspace=workspace,
            exception_type=exception_type,
            message=message,
            traceback_files=traceback_files,
            missing_module=missing_module,
            import_error_module=import_error_module,
            attribute_module=attribute_module,
            dependency_graph=dependency_graph,
        )
        primary_target = self._primary_target(root_cause, traceback_files)
        affected_files = self._affected_files(root_cause, traceback_files, missing_module)
        import_chain = self._import_chain(workspace, traceback_files, dependency_graph)
        reason = self._reason(
            exception_type,
            failure_class,
            missing_module,
            root_cause,
            workspace,
        )
        confidence = self._confidence(exception_type, root_cause)

        if self._should_use_verified_diagnosis(verified_diagnosis.to_dict()):
            diagnosis_payload = verified_diagnosis.to_dict()
            root_cause = diagnosis_payload["root_cause"]
            primary_target = diagnosis_payload["primary_target"]
            affected_files = diagnosis_payload["repair_targets"]
            failure_class = diagnosis_payload["failure_class"]
            reason = diagnosis_payload["reason"]
            confidence = diagnosis_payload["confidence"]

        return FailureAnalysis(
            exception_type=exception_type,
            message=message,
            failure_class=failure_class,
            root_cause=root_cause,
            primary_target=primary_target,
            reason=reason,
            confidence=confidence,
            affected_files=affected_files,
            import_chain=import_chain,
            missing_module=missing_module,
            workspace_tree=FixWorkspaceContextBuilder().build_tree(workspace),
            dependency_graph=dependency_graph,
            execution_contract=execution_contract or {},
            diagnostic_case={
                "failing_test_file": diagnostic_case.failing_test_file,
                "failing_production_file": diagnostic_case.failing_production_file,
                "previous_failure_signatures": diagnostic_case.previous_failure_signatures,
            },
            evidence_pack=diagnostic_case.evidence_pack(),
            hypotheses=[hypothesis.to_dict() for hypothesis in hypotheses],
            verified_diagnosis=verified_diagnosis.to_dict(),
        )

    def _should_use_verified_diagnosis(self, diagnosis: dict[str, Any]) -> bool:
        if diagnosis.get("confidence", 0) < 0.55:
            return False
        return diagnosis.get("diagnosis_id") == "production-export-mismatch"

    def _exception(self, output: str) -> tuple[str, str]:
        matches = EXCEPTION_PATTERN.findall(output)
        if not matches:
            return "UnknownError", output.strip()[:500]

        exception_type, message = matches[-1]
        return exception_type, message.strip()

    def _missing_module(self, output: str) -> str | None:
        match = MISSING_MODULE_PATTERN.search(output)
        return match.group(1) if match else None

    def _import_error_module(self, message: str) -> str | None:
        match = IMPORT_NAME_PATTERN.search(message)
        return match.group(2) if match else None

    def _attribute_error_module(self, message: str) -> str | None:
        match = ATTRIBUTE_MODULE_PATTERN.search(message)
        return match.group(1) if match else None

    def _failure_class(
        self,
        exception_type: str,
        message: str,
        execution_contract: dict[str, Any],
        contract_violations,
    ) -> str:
        if any(
            violation.code in {"invalid_python_import_root", "missing_python_import_root"}
            for violation in contract_violations
        ):
            return "InvalidExecutionContract"

        if exception_type == "ModuleNotFoundError":
            module_strategy = (execution_contract.get("module_strategy") or {}).get("type")
            if module_strategy and module_strategy not in {"none", "unknown"}:
                return "ImportOrModuleResolutionFailure"
            return "MissingModule"

        if exception_type == "ImportError":
            if IMPORT_NAME_PATTERN.search(message):
                return "MissingExport"
            return "ImportOrModuleResolutionFailure"

        if exception_type == "AttributeError":
            if ATTRIBUTE_MODULE_PATTERN.search(message):
                return "WrongObjectOrMissingAttribute"
            return "MissingAttribute"

        if exception_type == "TypeError":
            if "module" in message and "callable" in message:
                return "WrongObjectImported"
            return "TypeMismatch"

        if exception_type == "AssertionError":
            return "BehaviorMismatch"

        if exception_type == "SyntaxError":
            return "SyntaxError"

        if exception_type == "FileNotFoundError":
            return "MissingFile"

        return "UnknownFailure"

    def _traceback_files(self, workspace: Path, output: str) -> list[str]:
        files: list[str] = []

        for raw_path in FILE_PATTERN.findall(output) + SHORT_FILE_PATTERN.findall(output):
            path = Path(raw_path.replace("\\", "/"))
            relative = self._relative_to_workspace(workspace, path)
            if relative and relative not in files:
                files.append(relative)

        return files

    def _relative_to_workspace(self, workspace: Path, path: Path) -> str | None:
        try:
            if path.is_absolute():
                return path.resolve().relative_to(workspace.resolve()).as_posix()
        except (OSError, ValueError):
            return None

        parts = path.parts
        for anchor in ("app", "tests"):
            if anchor in parts:
                return Path(*parts[parts.index(anchor) :]).as_posix()

        return None

    def _dependency_graph(self, workspace: Path) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        app_root = workspace / "app"
        tests_root = workspace / "tests"

        for root in (app_root, tests_root):
            if not root.exists():
                continue
            for file_path in sorted(root.rglob("*.py")):
                if "__pycache__" in file_path.parts:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                imports = []
                for line in content.splitlines():
                    match = IMPORT_PATTERN.match(line)
                    if match:
                        imports.append(match.group(1) or match.group(2))

                graph[file_path.relative_to(workspace).as_posix()] = imports

        return graph

    def _root_cause(
        self,
        workspace: Path,
        exception_type: str,
        message: str,
        traceback_files: list[str],
        missing_module: str | None,
        import_error_module: str | None,
        attribute_module: str | None,
        dependency_graph: dict[str, list[str]],
    ) -> str | None:
        if exception_type == "SyntaxError":
            source_files = [path for path in traceback_files if not path.startswith("tests/")]
            if source_files:
                return source_files[-1]
            return traceback_files[-1] if traceback_files else None

        if exception_type == "AttributeError":
            attribute_target = self._module_to_existing_path(workspace, attribute_module)
            if attribute_target:
                return attribute_target

        if exception_type == "ImportError":
            import_target = self._module_to_existing_path(workspace, import_error_module)
            if import_target:
                return import_target

        importer = self._importer_for_missing_module(missing_module, dependency_graph)
        if importer:
            return importer

        package_root_candidate = self._package_root_candidate(workspace, missing_module)
        if package_root_candidate:
            return package_root_candidate

        source_files = [path for path in traceback_files if not path.startswith("tests/")]
        if source_files:
            return source_files[-1]

        if missing_module:
            missing_path = Path(*missing_module.split(".")).with_suffix(".py")
            candidate = missing_path.as_posix()
            if (workspace / candidate).exists():
                return candidate

        if exception_type == "AssertionError":
            assertion_target = self._production_import_from_tests(
                workspace,
                traceback_files,
                dependency_graph,
            )
            if assertion_target:
                return assertion_target

        if exception_type == "TypeError" and "module" in message and "callable" in message:
            callable_target = self._production_import_from_tests(
                workspace,
                traceback_files,
                dependency_graph,
            )
            if callable_target:
                return callable_target

        return traceback_files[-1] if traceback_files else None

    def _module_to_existing_path(self, workspace: Path, module: str | None) -> str | None:
        if not module:
            return None

        module_path = Path(*module.split("."))
        candidates = [
            workspace / module_path.with_suffix(".py"),
            workspace / module_path / "__init__.py",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate.relative_to(workspace).as_posix()

        return None

    def _production_import_from_tests(
        self,
        workspace: Path,
        traceback_files: list[str],
        dependency_graph: dict[str, list[str]],
    ) -> str | None:
        for file_path in traceback_files:
            if not file_path.startswith("tests/"):
                continue

            for import_name in dependency_graph.get(file_path, []):
                if not import_name.startswith("app"):
                    continue

                target = self._module_to_existing_path(workspace, import_name)
                if target and target.startswith("app/") and not target.endswith("__init__.py"):
                    return target

                package_member = workspace / Path(*import_name.split(".")) / "app.py"
                if package_member.exists():
                    return package_member.relative_to(workspace).as_posix()

        return None

    def _package_root_candidate(self, workspace: Path, missing_module: str | None) -> str | None:
        if not missing_module:
            return None

        parts = missing_module.split(".")
        if not parts or parts[0] == "app":
            return None

        for index in range(1, len(parts)):
            candidate = workspace / "app" / Path(*parts[index:]).with_suffix(".py")
            if candidate.exists():
                return candidate.relative_to(workspace).as_posix()

        return None

    def _importer_for_missing_module(
        self,
        missing_module: str | None,
        dependency_graph: dict[str, list[str]],
    ) -> str | None:
        if not missing_module:
            return None

        candidates = [
            missing_module,
            missing_module.rsplit(".", 1)[0] if "." in missing_module else missing_module,
        ]

        for file_path, imports in dependency_graph.items():
            if any(
                import_name in candidates
                or any(import_name.startswith(f"{candidate}.") for candidate in candidates)
                for import_name in imports
            ):
                return file_path

        return None

    def _primary_target(self, root_cause: str | None, traceback_files: list[str]) -> str | None:
        if root_cause and root_cause.startswith("app/"):
            return root_cause

        source_files = [path for path in traceback_files if path.startswith("app/")]
        if source_files:
            return source_files[-1]

        return root_cause

    def _affected_files(
        self,
        root_cause: str | None,
        traceback_files: list[str],
        missing_module: str | None,
    ) -> list[str]:
        affected = []
        for path in [root_cause, *traceback_files]:
            if path and path not in affected:
                affected.append(path)

        if missing_module:
            missing_path = Path(*missing_module.split(".")).with_suffix(".py").as_posix()
            if missing_path not in affected:
                affected.append(missing_path)

        return affected

    def _import_chain(
        self,
        workspace: Path,
        traceback_files: list[str],
        dependency_graph: dict[str, list[str]],
    ) -> list[str]:
        chain = list(traceback_files)

        for file_path in traceback_files:
            if not file_path.startswith("tests/"):
                continue
            for import_name in dependency_graph.get(file_path, []):
                if import_name.startswith("app") and import_name not in chain:
                    chain.append(import_name)
                target = self._module_to_existing_path(workspace, import_name)
                if target and target not in chain:
                    chain.append(target)

        return chain

    def _reason(
        self,
        exception_type: str,
        failure_class: str,
        missing_module: str | None,
        root_cause: str | None,
        workspace: Path,
    ) -> str:
        if failure_class == "WrongObjectOrMissingAttribute":
            return (
                "Flask app object is not exported/imported correctly; test receives "
                "a module-like object without the expected attribute."
            )

        if failure_class == "MissingExport":
            return "Production module does not export the symbol imported by the tests."

        if failure_class == "BehaviorMismatch" and root_cause and root_cause.startswith("app/"):
            return "Production behavior does not satisfy the generated test assertion."

        if exception_type == "SyntaxError":
            return "Syntax error in imported source file."

        if missing_module:
            if failure_class == "InvalidExecutionContract":
                return (
                    "Project Execution Contract contains invalid module semantics for "
                    f"missing module '{missing_module}'."
                )
            if failure_class == "ImportOrModuleResolutionFailure":
                return (
                    "Import or module resolution failed relative to the Project Execution "
                    f"Contract for missing module '{missing_module}'."
                )
            if missing_module.startswith("app."):
                return f"Missing dependency file for module '{missing_module}'."
            missing_path = workspace / Path(*missing_module.split(".")).with_suffix(".py")
            if not missing_path.exists():
                return f"Invalid package import for missing module '{missing_module}'."
            if root_cause and root_cause.startswith("app/"):
                return f"Invalid package import for missing module '{missing_module}'."

        if exception_type in {"ModuleNotFoundError", "ImportError"}:
            return "Import failure in generated project package hierarchy."

        return "Test failure requires repair planning."

    def _confidence(self, exception_type: str, root_cause: str | None) -> float:
        if root_cause and root_cause.startswith("app/"):
            if exception_type in {"AttributeError", "ImportError", "ModuleNotFoundError"}:
                return 0.85
            if exception_type == "SyntaxError":
                return 0.95
            if exception_type == "AssertionError":
                return 0.7

        if root_cause:
            return 0.55

        return 0.2
