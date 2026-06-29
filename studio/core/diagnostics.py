import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.contracts.execution import infer_execution_contract, validate_execution_contract
from studio.core.fix_prompt import FixWorkspaceContextBuilder
from studio.core.project_knowledge import ProjectKnowledgeGraphBuilder
from studio.core.tester_result import StageTestResult


@dataclass(frozen=True)
class DiagnosticCase:
    raw_tester_output: str
    traceback: str
    exception_type: str
    exception_message: str
    failing_test_file: str | None
    failing_production_file: str | None
    workspace_tree: str
    relevant_files: dict[str, str]
    project_graph: dict[str, Any]
    execution_contract: dict[str, Any]
    import_graph: dict[str, list[str]]
    latest_handoff: dict[str, Any] = field(default_factory=dict)
    original_requirements: str = ""
    previous_failure_signatures: list[str] = field(default_factory=list)

    def evidence_pack(self) -> dict[str, Any]:
        return {
            "traceback": self.traceback,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "failing_test_file": self.failing_test_file,
            "failing_production_file": self.failing_production_file,
            "workspace_tree": self.workspace_tree,
            "relevant_files": sorted(self.relevant_files),
            "project_graph": self.project_graph,
            "execution_contract": self.execution_contract,
            "import_graph": self.import_graph,
            "latest_handoff": self.latest_handoff,
            "original_requirements": self.original_requirements,
            "previous_failure_signatures": self.previous_failure_signatures,
        }


@dataclass(frozen=True)
class DiagnosticHypothesis:
    hypothesis_id: str
    failure_class: str
    candidate_root_cause: str
    candidate_repair_targets: list[str]
    supporting_evidence: list[str] = field(default_factory=list)
    evidence_needed: list[str] = field(default_factory=list)
    confidence: float = 0.4

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "failure_class": self.failure_class,
            "candidate_root_cause": self.candidate_root_cause,
            "candidate_repair_targets": self.candidate_repair_targets,
            "supporting_evidence": self.supporting_evidence,
            "evidence_needed": self.evidence_needed,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class VerifiedDiagnosis:
    diagnosis_id: str
    failure_class: str
    root_cause: str
    primary_target: str | None
    repair_targets: list[str]
    files_to_preserve: list[str] = field(default_factory=list)
    confidence: float = 0.5
    accepted_hypothesis: dict[str, Any] = field(default_factory=dict)
    rejected_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    evidence_summary: list[str] = field(default_factory=list)
    reason: str = ""
    symptom_location: str | None = None
    failing_location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "failure_class": self.failure_class,
            "root_cause": self.root_cause,
            "primary_target": self.primary_target,
            "repair_targets": self.repair_targets,
            "files_to_preserve": self.files_to_preserve,
            "confidence": self.confidence,
            "accepted_hypothesis": self.accepted_hypothesis,
            "rejected_hypotheses": self.rejected_hypotheses,
            "evidence_summary": self.evidence_summary,
            "reason": self.reason,
            "symptom_location": self.symptom_location,
            "failing_location": self.failing_location,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class DiagnosticCaseBuilder:
    def build(
        self,
        workspace_path: str | Path,
        tester_result: StageTestResult,
        exception_type: str,
        exception_message: str,
        traceback_files: list[str],
        import_graph: dict[str, list[str]],
        execution_contract: dict[str, Any] | None = None,
        project_state: dict[str, Any] | None = None,
        latest_handoff: dict[str, Any] | None = None,
        original_requirements: str = "",
        previous_failure_signatures: list[str] | None = None,
    ) -> DiagnosticCase:
        workspace = Path(workspace_path)
        raw_output = f"{tester_result.stdout}\n{tester_result.stderr}".strip()
        relevant_files = self._relevant_files(workspace, traceback_files, project_state)
        project_graph = (project_state or {}).get("project_graph") or self._project_graph(
            workspace,
            relevant_files,
        )
        contract = execution_contract or (project_state or {}).get(
            "execution_contract"
        ) or infer_execution_contract(
            workspace_path=workspace,
            project_graph=project_graph,
        ).to_dict()
        failing_test = next(
            (path for path in traceback_files if path.startswith("tests/")),
            None,
        )
        failing_source = next(
            (path for path in reversed(traceback_files) if path.startswith("app/")),
            None,
        )
        if failing_source is None:
            failing_source = self._production_target_from_test(
                relevant_files,
                import_graph,
                failing_test,
            )

        return DiagnosticCase(
            raw_tester_output=raw_output,
            traceback=raw_output,
            exception_type=exception_type,
            exception_message=exception_message,
            failing_test_file=failing_test,
            failing_production_file=failing_source,
            workspace_tree=self._workspace_tree(workspace, project_state),
            relevant_files=relevant_files,
            project_graph=project_graph,
            execution_contract=contract,
            import_graph=import_graph,
            latest_handoff=latest_handoff or {},
            original_requirements=original_requirements,
            previous_failure_signatures=previous_failure_signatures or [],
        )

    def _production_target_from_test(
        self,
        relevant_files: dict[str, str],
        import_graph: dict[str, list[str]],
        failing_test: str | None,
    ) -> str | None:
        if not failing_test:
            return None
        for imported in import_graph.get(failing_test, []):
            if imported == "app":
                content = relevant_files.get(failing_test, "")
                if "from app import main" in content and "app/main.py" in relevant_files:
                    return "app/main.py"
            if imported.startswith("app."):
                candidate = Path(*imported.split(".")).with_suffix(".py").as_posix()
                if candidate in relevant_files:
                    return candidate
        return None

    def _relevant_files(
        self,
        workspace: Path,
        traceback_files: list[str],
        project_state: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        state_files = self._files_from_project_state(project_state)
        if state_files:
            return state_files

        paths = []
        for relative in traceback_files:
            if relative not in paths:
                paths.append(relative)
        for root in ("app", "tests"):
            base = workspace / root
            if not base.exists():
                continue
            for path in sorted(base.rglob("*.py")):
                relative = path.relative_to(workspace).as_posix()
                if "__pycache__" not in path.parts and relative not in paths:
                    paths.append(relative)

        snippets = {}
        for relative in paths[:40]:
            path = workspace / relative
            if path.is_file():
                snippets[relative] = path.read_text(encoding="utf-8", errors="replace")[:8000]
        return snippets

    def _files_from_project_state(
        self,
        project_state: dict[str, Any] | None,
    ) -> dict[str, str]:
        if not project_state:
            return {}
        files = {}
        for item in (project_state.get("merged_files") or {}).get("files", []):
            path = item.get("path")
            if path:
                files[path] = item.get("content_preview", "")
        return files

    def _workspace_tree(
        self,
        workspace: Path,
        project_state: dict[str, Any] | None,
    ) -> str:
        if project_state:
            paths = [
                item.get("path")
                for item in (project_state.get("merged_files") or {}).get("files", [])
                if item.get("path")
            ]
            if paths:
                return "\n".join(sorted(paths))
        return FixWorkspaceContextBuilder().build_tree(workspace)

    def _project_graph(self, workspace: Path, relevant_files: dict[str, str]) -> dict[str, Any]:
        source_files = [path for path in relevant_files if path.startswith("app/")]
        test_files = [path for path in relevant_files if path.startswith("tests/")]
        if not workspace.exists():
            return ProjectKnowledgeGraphBuilder().empty()
        dependency_files = [
            path.name
            for path in workspace.iterdir()
            if path.name in {"requirements.txt", "pyproject.toml", "package.json", "go.mod"}
        ]
        return ProjectKnowledgeGraphBuilder().build(
            workspace,
            source_files,
            test_files,
            dependency_files,
            [],
            [],
        )


class HypothesisGenerator:
    def generate(self, case: DiagnosticCase) -> list[DiagnosticHypothesis]:
        hypotheses = []
        if case.exception_type == "TypeError" and "module" in case.exception_message:
            hypotheses.extend(self._module_callable_hypotheses(case))
        if case.exception_type in {"ModuleNotFoundError", "ImportError"}:
            hypotheses.append(
                DiagnosticHypothesis(
                    "import-resolution",
                    "ImportOrModuleResolutionFailure",
                    case.failing_production_file or case.failing_test_file or "unknown",
                    self._balanced_targets(case),
                    ["Import failure surfaced during test import chain."],
                    ["Verify import root and target module existence."],
                    0.65,
                )
            )
        if case.exception_type == "SyntaxError":
            target = case.failing_production_file or case.failing_test_file or "unknown"
            hypotheses.append(
                DiagnosticHypothesis(
                    "syntax-error-source",
                    "SyntaxError",
                    target,
                    [target],
                    ["Traceback points to a syntax error in parsed source."],
                    [],
                    0.95,
                )
            )
        if case.exception_type == "AssertionError":
            target = self._production_import_from_test(case) or case.failing_test_file or "unknown"
            hypotheses.append(
                DiagnosticHypothesis(
                    "behavior-mismatch",
                    "BehaviorMismatch",
                    target,
                    self._balanced_targets(case, preferred=target),
                    ["Assertion failed after project code executed."],
                    ["Compare assertion with original requirements."],
                    0.7,
                )
            )
        if not hypotheses:
            hypotheses.append(
                DiagnosticHypothesis(
                    "insufficient-evidence",
                    "UnknownFailure",
                    case.failing_production_file or case.failing_test_file or "unknown",
                    self._balanced_targets(case),
                    ["No specialized hypothesis matched."],
                    ["Collect more execution evidence."],
                    0.25,
                )
            )
        return hypotheses

    def _module_callable_hypotheses(self, case: DiagnosticCase) -> list[DiagnosticHypothesis]:
        targets = self._balanced_targets(case)
        return [
            DiagnosticHypothesis(
                "production-export-mismatch",
                "ImportOrModuleResolutionFailure",
                "Import/export contract mismatch between test and production module.",
                targets,
                [
                    "TypeError reports a module object was called as a function.",
                    "Failing test likely imported a module and called it as callable.",
                ],
                ["Verify expected callable exists in imported production module."],
                0.72,
            ),
            DiagnosticHypothesis(
                "test-calls-module",
                "TestInterfaceMismatch",
                case.failing_test_file or "unknown",
                [case.failing_test_file] if case.failing_test_file else [],
                ["The exception surfaced in the failing test file."],
                ["Check whether test contradicts requirements or execution contract."],
                0.42,
            ),
        ]

    def _balanced_targets(
        self,
        case: DiagnosticCase,
        preferred: str | None = None,
    ) -> list[str]:
        targets = []
        for path in (preferred, case.failing_production_file):
            if path and path not in targets:
                targets.append(path)
        if "app/__init__.py" in case.relevant_files and "app/__init__.py" not in targets:
            targets.append("app/__init__.py")
        if case.failing_test_file and case.failing_test_file not in targets:
            targets.append(case.failing_test_file)
        return targets

    def _production_import_from_test(self, case: DiagnosticCase) -> str | None:
        if not case.failing_test_file:
            return None
        for imported in case.import_graph.get(case.failing_test_file, []):
            if imported.startswith("app."):
                candidate = Path(*imported.split(".")).with_suffix(".py").as_posix()
                if candidate in case.relevant_files:
                    return candidate
        return case.failing_production_file


class HypothesisVerifier:
    def verify(
        self,
        case: DiagnosticCase,
        hypotheses: list[DiagnosticHypothesis],
    ) -> VerifiedDiagnosis:
        accepted = None
        rejected = []
        for hypothesis in hypotheses:
            score, evidence = self._score(case, hypothesis)
            payload = hypothesis.to_dict()
            payload["verified_confidence"] = score
            payload["verification_evidence"] = evidence
            if accepted is None or score > accepted[0]:
                if accepted is not None:
                    rejected.append(accepted[1])
                accepted = (score, payload)
            else:
                rejected.append(payload)

        if accepted is None:
            accepted = (0.2, hypotheses[0].to_dict())
        confidence, hypothesis_payload = accepted
        targets = self._verified_targets(case, hypothesis_payload, confidence)
        primary_target = next((path for path in targets if path.startswith("app/")), None)
        if primary_target is None:
            primary_target = targets[0] if targets else None
        failure_class = hypothesis_payload.get("failure_class", "UnknownFailure")

        return VerifiedDiagnosis(
            diagnosis_id=hypothesis_payload.get("hypothesis_id", "unknown"),
            failure_class=failure_class,
            root_cause=hypothesis_payload.get("candidate_root_cause") or "unknown",
            primary_target=primary_target,
            repair_targets=targets,
            files_to_preserve=self._files_to_preserve(case),
            confidence=confidence,
            accepted_hypothesis=hypothesis_payload,
            rejected_hypotheses=rejected,
            evidence_summary=hypothesis_payload.get("verification_evidence", []),
            reason=self._reason(case, hypothesis_payload, confidence),
            symptom_location=case.failing_test_file,
            failing_location=case.failing_production_file or case.failing_test_file,
        )

    def _score(
        self,
        case: DiagnosticCase,
        hypothesis: DiagnosticHypothesis,
    ) -> tuple[float, list[str]]:
        evidence = list(hypothesis.supporting_evidence)
        confidence = hypothesis.confidence
        contract_violations = validate_execution_contract(case.execution_contract)
        if contract_violations:
            confidence += 0.08
            evidence.append("Execution contract has validation findings.")
        if hypothesis.hypothesis_id == "production-export-mismatch":
            if self._test_calls_imported_module(case):
                confidence += 0.18
                evidence.append("Test imports a production module name and calls it as a function.")
            if self._expected_callable_missing(case):
                confidence += 0.12
                evidence.append(
                    "Production module does not expose the callable expected by the test."
                )
            if case.failing_test_file:
                evidence.append("The test file is treated as symptom location, not root cause.")
        elif hypothesis.hypothesis_id == "test-calls-module":
            if not self._test_contradicts_requirements(case):
                confidence -= 0.18
                evidence.append("No evidence shows the test contradicts original requirements.")
            if case.failing_production_file:
                confidence -= 0.1
                evidence.append(
                    "Traceback includes production code, so blaming only the test is weak."
                )
        return max(0.05, min(confidence, 0.98)), evidence

    def _verified_targets(
        self,
        case: DiagnosticCase,
        hypothesis: dict[str, Any],
        confidence: float,
    ) -> list[str]:
        targets = list(hypothesis.get("candidate_repair_targets") or [])
        if confidence < 0.55:
            for path in (case.failing_production_file, "app/__init__.py", case.failing_test_file):
                if path and path in case.relevant_files and path not in targets:
                    targets.append(path)
        if hypothesis.get("hypothesis_id") == "production-export-mismatch":
            for path in (case.failing_production_file, "app/__init__.py", case.failing_test_file):
                if path and path in case.relevant_files and path not in targets:
                    targets.append(path)
        return [target for target in targets if target and target != "unknown"]

    def _test_calls_imported_module(self, case: DiagnosticCase) -> bool:
        if not case.failing_test_file:
            return False
        content = case.relevant_files.get(case.failing_test_file, "")
        return "from app import main" in content and "main(" in content

    def _expected_callable_missing(self, case: DiagnosticCase) -> bool:
        source = case.relevant_files.get("app/main.py") or ""
        if not source:
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        return not any(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "main"
            for node in ast.walk(tree)
        )

    def _test_contradicts_requirements(self, case: DiagnosticCase) -> bool:
        if not case.original_requirements:
            return False
        return "do not call main" in case.original_requirements.lower()

    def _files_to_preserve(self, case: DiagnosticCase) -> list[str]:
        return [
            path
            for path in ("requirements.txt", "RUN.md", "README.md")
            if path in case.relevant_files or path in case.workspace_tree
        ]

    def _reason(self, case: DiagnosticCase, hypothesis: dict[str, Any], confidence: float) -> str:
        if hypothesis.get("hypothesis_id") == "production-export-mismatch":
            return (
                "The test calls main(), but the imported name resolves to a module-like object; "
                "production exports and the test import contract disagree."
            )
        if confidence < 0.55:
            return "Diagnosis has limited evidence; repair planning should keep broader targets."
        return "Verified diagnosis selected from evidence-backed hypotheses."
