import re
from dataclasses import dataclass, field
from pathlib import Path

from studio.core.fix_prompt import FixWorkspaceContextBuilder
from studio.core.tester_result import StageTestResult

IMPORT_PATTERN = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+|import\s+([\w.]+))")
FILE_PATTERN = re.compile(r'File "([^"]+\.py)"')
SHORT_FILE_PATTERN = re.compile(r"((?:app|tests)[/\\][\w./\\-]+\.py)")
EXCEPTION_PATTERN = re.compile(r"(?m)^([A-Za-z_][\w.]*Error|SyntaxError|ImportError):\s*(.*)$")
MISSING_MODULE_PATTERN = re.compile(r"No module named ['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class FailureAnalysis:
    exception_type: str
    message: str
    root_cause: str | None
    reason: str
    affected_files: list[str] = field(default_factory=list)
    import_chain: list[str] = field(default_factory=list)
    missing_module: str | None = None
    workspace_tree: str = ""
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "exception_type": self.exception_type,
            "message": self.message,
            "root_cause": self.root_cause,
            "reason": self.reason,
            "affected_files": self.affected_files,
            "import_chain": self.import_chain,
            "missing_module": self.missing_module,
            "workspace_tree": self.workspace_tree,
            "dependency_graph": self.dependency_graph,
        }


class FailureAnalyzer:
    def analyze(
        self,
        workspace_path: str | Path,
        tester_result: StageTestResult,
        bug_report: str = "",
    ) -> FailureAnalysis:
        workspace = Path(workspace_path)
        output = f"{tester_result.stdout}\n{tester_result.stderr}\n{bug_report}"
        exception_type, message = self._exception(output)
        missing_module = self._missing_module(output)
        traceback_files = self._traceback_files(workspace, output)
        dependency_graph = self._dependency_graph(workspace)

        root_cause = self._root_cause(
            workspace=workspace,
            exception_type=exception_type,
            traceback_files=traceback_files,
            missing_module=missing_module,
            dependency_graph=dependency_graph,
        )
        affected_files = self._affected_files(root_cause, traceback_files, missing_module)
        reason = self._reason(exception_type, missing_module, root_cause, workspace)

        return FailureAnalysis(
            exception_type=exception_type,
            message=message,
            root_cause=root_cause,
            reason=reason,
            affected_files=affected_files,
            import_chain=traceback_files,
            missing_module=missing_module,
            workspace_tree=FixWorkspaceContextBuilder().build_tree(workspace),
            dependency_graph=dependency_graph,
        )

    def _exception(self, output: str) -> tuple[str, str]:
        matches = EXCEPTION_PATTERN.findall(output)
        if not matches:
            return "UnknownError", output.strip()[:500]

        exception_type, message = matches[-1]
        return exception_type, message.strip()

    def _missing_module(self, output: str) -> str | None:
        match = MISSING_MODULE_PATTERN.search(output)
        return match.group(1) if match else None

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
        traceback_files: list[str],
        missing_module: str | None,
        dependency_graph: dict[str, list[str]],
    ) -> str | None:
        if exception_type == "SyntaxError":
            source_files = [path for path in traceback_files if not path.startswith("tests/")]
            if source_files:
                return source_files[-1]
            return traceback_files[-1] if traceback_files else None

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

        return traceback_files[-1] if traceback_files else None

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

    def _reason(
        self,
        exception_type: str,
        missing_module: str | None,
        root_cause: str | None,
        workspace: Path,
    ) -> str:
        if exception_type == "SyntaxError":
            return "Syntax error in imported source file."

        if missing_module:
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
