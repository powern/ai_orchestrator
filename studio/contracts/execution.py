import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandContract:
    required: bool = False
    command: str | None = None
    working_directory: str = "."
    expected_artifacts: list[str] = field(default_factory=list)
    host: str | None = None
    port: int | None = None
    expected_ready_signal: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "required": self.required,
            "command": self.command,
            "working_directory": self.working_directory,
            "expected_artifacts": self.expected_artifacts,
        }
        if self.host is not None:
            payload["host"] = self.host
        if self.port is not None:
            payload["port"] = self.port
        if self.expected_ready_signal is not None:
            payload["expected_ready_signal"] = self.expected_ready_signal
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "CommandContract":
        value = value or {}
        return cls(
            required=bool(value.get("required", False)),
            command=value.get("command"),
            working_directory=value.get("working_directory") or ".",
            expected_artifacts=list(value.get("expected_artifacts") or []),
            host=value.get("host"),
            port=value.get("port"),
            expected_ready_signal=value.get("expected_ready_signal"),
        )


@dataclass(frozen=True)
class ModuleStrategy:
    type: str = "unknown"
    import_root: str | None = None
    namespace_root: str | None = None
    include_roots: list[str] = field(default_factory=list)
    module_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "import_root": self.import_root,
            "namespace_root": self.namespace_root,
            "include_roots": self.include_roots,
            "module_file": self.module_file,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ModuleStrategy":
        value = value or {}
        return cls(
            type=value.get("type") or "unknown",
            import_root=value.get("import_root"),
            namespace_root=value.get("namespace_root"),
            include_roots=list(value.get("include_roots") or []),
            module_file=value.get("module_file"),
        )


@dataclass(frozen=True)
class ArtifactContract:
    expected_files: list[str] = field(default_factory=list)
    expected_directories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_files": self.expected_files,
            "expected_directories": self.expected_directories,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ArtifactContract":
        value = value or {}
        return cls(
            expected_files=list(value.get("expected_files") or []),
            expected_directories=list(value.get("expected_directories") or []),
        )


@dataclass(frozen=True)
class ProjectExecutionContract:
    language: str = "unknown"
    project_root: str = "."
    source_roots: list[str] = field(default_factory=list)
    test_roots: list[str] = field(default_factory=list)
    build: CommandContract = field(default_factory=CommandContract)
    run: CommandContract = field(default_factory=lambda: CommandContract(required=False))
    test: CommandContract = field(default_factory=lambda: CommandContract(required=True))
    module_strategy: ModuleStrategy = field(default_factory=ModuleStrategy)
    artifacts: ArtifactContract = field(default_factory=ArtifactContract)

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "project_root": self.project_root,
            "source_roots": self.source_roots,
            "test_roots": self.test_roots,
            "build": self.build.to_dict(),
            "run": self.run.to_dict(),
            "test": self.test.to_dict(),
            "module_strategy": self.module_strategy.to_dict(),
            "artifacts": self.artifacts.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ProjectExecutionContract":
        value = value or {}
        return cls(
            language=value.get("language") or "unknown",
            project_root=value.get("project_root") or ".",
            source_roots=list(value.get("source_roots") or []),
            test_roots=list(value.get("test_roots") or []),
            build=CommandContract.from_dict(value.get("build")),
            run=CommandContract.from_dict(value.get("run")),
            test=CommandContract.from_dict(value.get("test")),
            module_strategy=ModuleStrategy.from_dict(value.get("module_strategy")),
            artifacts=ArtifactContract.from_dict(value.get("artifacts")),
        )


@dataclass(frozen=True)
class ExecutionContractViolation:
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


def infer_execution_contract(
    workspace_path: str | Path | None = None,
    workspace_state: dict[str, Any] | None = None,
    project_graph: dict[str, Any] | None = None,
    executor_actions: list[dict[str, Any]] | None = None,
) -> ProjectExecutionContract:
    graph = project_graph or (workspace_state or {}).get("project_graph") or {}
    state = workspace_state or {}
    action_paths = [
        action.get("path")
        for action in executor_actions or []
        if isinstance(action, dict) and action.get("action") == "write_file" and action.get("path")
    ]
    action_commands = [
        action.get("command")
        for action in executor_actions or []
        if isinstance(action, dict) and action.get("action") == "run" and action.get("command")
    ]
    dependency_files = list(state.get("dependency_files") or [])
    source_files = list((state.get("source_files") or {}).get("files") or [])
    test_files = list((state.get("tests") or {}).get("files") or [])
    if workspace_path and not (source_files or test_files or dependency_files):
        scanned = _scan_workspace(Path(workspace_path))
        source_files = scanned["source_files"]
        test_files = scanned["test_files"]
        dependency_files = scanned["dependency_files"]

    if not source_files and action_paths:
        source_files = [path for path in action_paths if _looks_like_source_file(path)]
    if not test_files and action_paths:
        test_files = [path for path in action_paths if _looks_like_test_file(path)]
    if not dependency_files and action_paths:
        dependency_files = [path for path in action_paths if _looks_like_dependency_file(path)]

    project_types = set((graph.get("summary") or {}).get("project_types") or [])
    project_types.update(state.get("project_type_hints") or [])
    language = _language(project_types, dependency_files, source_files, action_paths)
    source_roots = _roots(source_files)
    test_roots = _roots(test_files)
    entrypoints = graph.get("entrypoints") or []
    run_command = _first_runtime_command(action_commands)
    if not run_command and entrypoints:
        run_command = _run_command_for_entrypoint(language, entrypoints[0].get("path"))
    if not run_command:
        run_command = _known_run_command(action_paths, workspace_path)
    test_command = _first_test_command(action_commands) or _default_test_command(language)
    build_command = _default_build_command(language, dependency_files, action_paths)
    framework = _framework(project_types, graph)
    module_strategy = _module_strategy(language, graph, source_roots, dependency_files)

    return ProjectExecutionContract(
        language=language,
        project_root=".",
        source_roots=source_roots,
        test_roots=test_roots,
        build=CommandContract(
            required=bool(build_command),
            command=build_command,
            working_directory=".",
            expected_artifacts=_expected_build_artifacts(language),
        ),
        run=CommandContract(
            required=bool(run_command),
            command=run_command,
            working_directory=".",
            host="0.0.0.0" if framework in {"flask", "fastapi"} else None,
            port=5000 if framework == "flask" else None,
        ),
        test=CommandContract(
            required=bool(test_command),
            command=test_command,
            working_directory=".",
        ),
        module_strategy=module_strategy,
        artifacts=ArtifactContract(
            expected_files=sorted(set(dependency_files)),
            expected_directories=sorted(set(source_roots + test_roots)),
        ),
    )


def validate_execution_contract(
    contract: ProjectExecutionContract | dict[str, Any] | None,
    workspace_path: str | Path | None = None,
    planned_files: list[str] | None = None,
) -> list[ExecutionContractViolation]:
    if contract is None:
        return []
    if isinstance(contract, dict):
        contract = ProjectExecutionContract.from_dict(contract)
    workspace = Path(workspace_path) if workspace_path else None
    planned = set(planned_files or [])
    violations: list[ExecutionContractViolation] = []

    _validate_command("build", contract.build, contract, workspace, planned, violations)
    _validate_command("run", contract.run, contract, workspace, planned, violations)
    _validate_command("test", contract.test, contract, workspace, planned, violations)

    for root in contract.source_roots:
        _validate_path_reference("source_root", root, workspace, planned, violations)
    for root in contract.test_roots:
        _validate_path_reference("test_root", root, workspace, planned, violations)

    if contract.language == "python":
        _validate_python(contract, workspace, planned, violations)
    elif contract.language == "csharp":
        _validate_csharp(contract, workspace, planned, violations)
    elif contract.language == "cpp":
        _validate_cpp(contract, workspace, planned, violations)

    return violations


def _validate_command(
    name: str,
    command: CommandContract,
    contract: ProjectExecutionContract,
    workspace: Path | None,
    planned: set[str],
    violations: list[ExecutionContractViolation],
) -> None:
    if command.required and not command.command:
        violations.append(
            ExecutionContractViolation(
                f"missing_{name}_command",
                f"{name} command is required but missing.",
            )
        )
    _validate_path_reference(
        f"{name}_working_directory",
        command.working_directory,
        workspace,
        planned,
        violations,
        allow_file=False,
    )
    if name == "run" and command.command:
        command_path = _command_path(command.command)
        if command_path and contract.language in {"python", "unknown"}:
            _validate_path_reference(
                "run_command_path",
                command_path,
                workspace,
                planned,
                violations,
            )


def _validate_python(
    contract: ProjectExecutionContract,
    workspace: Path | None,
    planned: set[str],
    violations: list[ExecutionContractViolation],
) -> None:
    import_root = contract.module_strategy.import_root
    if import_root and not _valid_python_module_path(import_root):
        violations.append(
            ExecutionContractViolation(
                "invalid_python_import_root",
                f"Python import_root '{import_root}' is not a valid import path.",
            )
        )
    if import_root:
        root_path = import_root.replace(".", "/")
        _validate_path_reference("python_import_root", root_path, workspace, planned, violations)
    if contract.run.command:
        command_path = _command_path(contract.run.command)
        if command_path and command_path.endswith(".py"):
            _validate_path_reference(
                "python_run_command",
                command_path,
                workspace,
                planned,
                violations,
            )


def _validate_csharp(
    contract: ProjectExecutionContract,
    workspace: Path | None,
    planned: set[str],
    violations: list[ExecutionContractViolation],
) -> None:
    files = _all_known_files(workspace, planned)
    if not any(path.endswith((".csproj", ".sln")) for path in files):
        violations.append(
            ExecutionContractViolation(
                "missing_dotnet_project_file",
                "C# execution contract requires a .csproj or .sln file.",
            )
        )
    commands = " ".join(
        command.command or "" for command in (contract.build, contract.run, contract.test)
    )
    if "dotnet" not in commands:
        violations.append(
            ExecutionContractViolation(
                "missing_dotnet_command",
                "C# execution contract should use dotnet build/test/run commands.",
            )
        )


def _validate_cpp(
    contract: ProjectExecutionContract,
    workspace: Path | None,
    planned: set[str],
    violations: list[ExecutionContractViolation],
) -> None:
    files = _all_known_files(workspace, planned)
    if "CMakeLists.txt" not in files and not contract.build.command:
        violations.append(
            ExecutionContractViolation(
                "missing_cpp_build_contract",
                "C++ execution contract requires CMakeLists.txt or a declared build command.",
            )
        )
    if (
        contract.build.required
        and contract.build.command
        and "cmake" not in contract.build.command
    ):
        violations.append(
            ExecutionContractViolation(
                "unexpected_cpp_build_command",
                "C++ build command should declare the selected build system.",
                severity="warning",
            )
        )


def _validate_path_reference(
    code: str,
    relative: str | None,
    workspace: Path | None,
    planned: set[str],
    violations: list[ExecutionContractViolation],
    allow_file: bool = True,
) -> None:
    if not relative or relative == ".":
        return
    normalized = relative.replace("\\", "/").strip("/")
    if normalized in planned or any(path.startswith(f"{normalized}/") for path in planned):
        return
    if planned and workspace is None:
        violations.append(
            ExecutionContractViolation(
                f"missing_{code}",
                f"Execution contract references missing path '{normalized}'.",
            )
        )
        return
    if workspace is None:
        return
    candidate = workspace / normalized
    exists = candidate.exists() and (allow_file or candidate.is_dir())
    if not exists:
        violations.append(
            ExecutionContractViolation(
                f"missing_{code}",
                f"Execution contract references missing path '{normalized}'.",
            )
        )


def _language(
    project_types: set[str],
    dependency_files: list[str],
    source_files: list[str],
    action_paths: list[str],
) -> str:
    files = dependency_files + source_files + action_paths
    if "node" in project_types or "package.json" in files:
        return "node"
    if "go" in project_types or "go.mod" in files:
        return "go"
    if any(path.endswith((".csproj", ".sln", ".cs")) for path in files):
        return "csharp"
    if any(path.endswith((".cpp", ".cc", ".cxx", ".hpp", ".h")) for path in files):
        return "cpp"
    if any(path.endswith(".java") for path in files):
        return "java"
    if "python" in project_types or any(path.endswith(".py") for path in files):
        return "python"
    return "unknown"


def _module_strategy(
    language: str,
    graph: dict[str, Any],
    source_roots: list[str],
    dependency_files: list[str],
) -> ModuleStrategy:
    if language == "python":
        return ModuleStrategy(
            type="python_imports",
            import_root=_package_root(graph, source_roots),
        )
    if language == "csharp":
        namespace = next((root for root in source_roots if root), None)
        return ModuleStrategy(type="dotnet_namespace", namespace_root=namespace)
    if language == "cpp":
        include_roots = [root for root in ("include", "src") if root in source_roots]
        return ModuleStrategy(type="cpp_include", include_roots=include_roots or source_roots)
    if language == "node":
        module_file = "package.json" if "package.json" in dependency_files else None
        return ModuleStrategy(type="node_module", module_file=module_file)
    if language == "go":
        return ModuleStrategy(type="go_module", module_file="go.mod")
    if language == "java":
        namespace = next((root for root in source_roots if root), None)
        return ModuleStrategy(type="java_package", namespace_root=namespace)
    return ModuleStrategy(type="unknown")


def _package_root(graph: dict[str, Any], source_roots: list[str]) -> str | None:
    packages = [
        package.get("name") for package in graph.get("packages", []) if package.get("name")
    ]
    if "app" in packages:
        return "app"
    if packages:
        return packages[0]
    if "app" in source_roots:
        return "app"
    return source_roots[0] if source_roots else None


def _roots(paths: list[str]) -> list[str]:
    roots = []
    for path in paths:
        root = path.split("/", 1)[0]
        if root and root not in roots:
            roots.append(root)
    return roots


def _framework(project_types: set[str], graph: dict[str, Any]) -> str | None:
    for framework in ("flask", "fastapi", "django"):
        if framework in project_types:
            return framework
    for module in graph.get("modules", []):
        if module.get("framework"):
            return module["framework"]
    return None


def _looks_like_source_file(path: str) -> bool:
    return not _looks_like_test_file(path) and path.endswith(
        (".py", ".cs", ".cpp", ".h", ".java")
    )


def _looks_like_test_file(path: str) -> bool:
    return path.startswith("tests/") or "/test" in path or path.endswith("Tests.cs")


def _looks_like_dependency_file(path: str) -> bool:
    return path in {
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
    }


def _first_runtime_command(commands: list[str]) -> str | None:
    for command in commands:
        if not _is_test_command(command) and any(
            marker in command
            for marker in ("python ", "dotnet run", "npm start", "go run", "java ")
        ):
            return command
    return None


def _first_test_command(commands: list[str]) -> str | None:
    for command in commands:
        if _is_test_command(command):
            return command
    return None


def _is_test_command(command: str) -> bool:
    return any(
        marker in command
        for marker in ("pytest", "dotnet test", "ctest", "go test", "npm test")
    )


def _run_command_for_entrypoint(language: str, path: str | None) -> str | None:
    if not path:
        return None
    if language == "python":
        return f"python {path}"
    if language == "go":
        return f"go run {path}"
    return None


def _known_run_command(action_paths: list[str], workspace_path: str | Path | None) -> str | None:
    for path in ("app/main.py", "app.py", "main.py"):
        if path in action_paths:
            return f"python {path}"
        if workspace_path and _has_python_main_guard(Path(workspace_path) / path):
            return f"python {path}"
    if "package.json" in action_paths or (
        workspace_path and (Path(workspace_path) / "package.json").exists()
    ):
        return "npm start"
    return None


def _has_python_main_guard(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content


def _default_test_command(language: str) -> str | None:
    return {
        "python": "pytest -q",
        "csharp": "dotnet test",
        "cpp": "ctest --test-dir build --output-on-failure",
        "node": "npm test",
        "go": "go test ./...",
        "java": "mvn test",
    }.get(language)


def _default_build_command(
    language: str,
    dependency_files: list[str],
    action_paths: list[str],
) -> str | None:
    files = set(dependency_files + action_paths)
    if language == "csharp":
        return "dotnet build"
    if language == "cpp" and "CMakeLists.txt" in files:
        return "cmake -S . -B build && cmake --build build"
    if language == "java":
        return "mvn test" if "pom.xml" in files else None
    return None


def _expected_build_artifacts(language: str) -> list[str]:
    return {
        "csharp": ["bin", "obj"],
        "cpp": ["build"],
        "node": ["node_modules"],
    }.get(language, [])


def _command_path(command: str) -> str | None:
    parts = command.split()
    for part in parts[1:]:
        cleaned = part.strip("'\"")
        if cleaned.endswith((".py", ".csproj", ".sln")):
            return cleaned.replace("\\", "/")
    return None


def _valid_python_module_path(value: str) -> bool:
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    return bool(re.fullmatch(rf"{identifier}(?:\.{identifier})*", value))


def _all_known_files(workspace: Path | None, planned: set[str]) -> set[str]:
    files = set(planned)
    if workspace and workspace.exists():
        files.update(
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
        )
    return files


def _scan_workspace(workspace: Path) -> dict[str, list[str]]:
    source_files = []
    test_files = []
    dependency_files = []
    if not workspace.exists():
        return {
            "source_files": source_files,
            "test_files": test_files,
            "dependency_files": dependency_files,
        }
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(workspace).as_posix()
        if _looks_like_dependency_file(relative):
            dependency_files.append(relative)
        elif path.suffix == ".py":
            if _looks_like_test_file(relative):
                test_files.append(relative)
            else:
                source_files.append(relative)
        elif path.suffix in {".cs", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".java"}:
            source_files.append(relative)
        elif path.name in {"CMakeLists.txt"} or path.suffix in {".csproj", ".sln"}:
            dependency_files.append(relative)
    return {
        "source_files": source_files,
        "test_files": test_files,
        "dependency_files": dependency_files,
    }
