import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from studio.contracts.execution import infer_execution_contract
from studio.contracts.project_specification import build_project_specification
from studio.core.workspace_observer import WorkspaceObserver

TEXT_SUFFIXES = {
    "",
    ".cs",
    ".css",
    ".go",
    ".html",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
}

EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "venv"}
MAX_FILE_PREVIEW = 800
MAX_MERGED_FILES = 120


@dataclass(frozen=True)
class ProjectStateFile:
    path: str
    source: str
    content_preview: str = ""
    exists_on_disk: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source": self.source,
            "content_preview": self.content_preview,
            "exists_on_disk": self.exists_on_disk,
        }


@dataclass(frozen=True)
class ProjectState:
    run_id: int | None
    project_id: int | None
    workspace_path: str
    actual_files: dict[str, Any]
    planned_files: dict[str, Any]
    merged_files: dict[str, Any]
    executor_actions: list[dict[str, Any]]
    project_graph: dict[str, Any]
    execution_contract: dict[str, Any]
    project_specification: dict[str, Any] = field(default_factory=dict)
    decision_history: list[dict[str, Any]] = field(default_factory=list)
    validation_evidence: dict[str, Any] = field(default_factory=dict)
    diagnostic_evidence: dict[str, Any] = field(default_factory=dict)
    state_source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "workspace_path": self.workspace_path,
            "actual_files": self.actual_files,
            "planned_files": self.planned_files,
            "merged_files": self.merged_files,
            "executor_actions": self.executor_actions,
            "project_graph": self.project_graph,
            "execution_contract": self.execution_contract,
            "project_specification": self.project_specification,
            "decision_history": self.decision_history,
            "validation_evidence": self.validation_evidence,
            "diagnostic_evidence": self.diagnostic_evidence,
            "state_source": self.state_source,
            "summary": self.summary(),
        }

    def summary(self) -> dict[str, Any]:
        graph_summary = self.project_graph.get("summary", {})
        return {
            "actual_file_count": self.actual_files.get("count", 0),
            "planned_file_count": self.planned_files.get("count", 0),
            "merged_file_count": self.merged_files.get("count", 0),
            "graph_source": self.state_source.get("graph_source"),
            "contract_source": self.state_source.get("contract_source"),
            "project_types": graph_summary.get("project_types", []),
            "entrypoints": [
                entry.get("path") for entry in self.project_graph.get("entrypoints", [])
            ],
            "routes": [route.get("path") for route in self.project_graph.get("routes", [])],
            "source_roots": self.execution_contract.get("source_roots", []),
            "test_roots": self.execution_contract.get("test_roots", []),
            "language": self.execution_contract.get("language", "unknown"),
            "framework": self.project_specification.get("framework", "unknown"),
            "project_type": self.project_specification.get("project_type", "unknown"),
            "specification_confidence": self.project_specification.get("confidence", 0.0),
        }


class ProjectStateBuilder:
    def build(
        self,
        run_id: int | None = None,
        project_id: int | None = None,
        workspace_path: str | Path | None = None,
        executor_actions: list[dict[str, Any]] | str | None = None,
        stage_outputs: dict[str, Any] | None = None,
        handoff_history: list[dict[str, Any]] | None = None,
        project_specification: dict[str, Any] | None = None,
        request_text: str | None = None,
    ) -> ProjectState:
        workspace = Path(workspace_path) if workspace_path else None
        actions = self._actions(executor_actions)
        actual_map = self._actual_files(workspace)
        planned_map = self._planned_files(actions)
        merged_map = dict(planned_map)
        merged_map.update(actual_map)

        graph_source = "merged_files" if merged_map else "empty"
        with tempfile.TemporaryDirectory(prefix="ai_orchestrator_project_state_") as temp_name:
            virtual_workspace = Path(temp_name)
            self._materialize_files(virtual_workspace, merged_map)
            observation = WorkspaceObserver().observe(virtual_workspace)

        spec = project_specification or build_project_specification(request_text).to_dict()
        execution_contract = infer_execution_contract(
            workspace_state=observation,
            project_graph=observation.get("project_graph", {}),
            executor_actions=actions,
            project_specification=spec,
        ).to_dict()

        return ProjectState(
            run_id=run_id,
            project_id=project_id,
            workspace_path=str(workspace_path or ""),
            actual_files=self._file_section(actual_map, "filesystem"),
            planned_files=self._file_section(planned_map, "executor_actions"),
            merged_files=self._merged_section(actual_map, planned_map),
            executor_actions=actions,
            project_graph=observation.get("project_graph", {}),
            execution_contract=execution_contract,
            project_specification=spec,
            decision_history=handoff_history or [],
            validation_evidence=stage_outputs or {},
            diagnostic_evidence={},
            state_source={
                "has_workspace": bool(workspace and workspace.exists()),
                "has_planned_actions": bool(planned_map),
                "graph_source": graph_source,
                "contract_source": "merged_files+decisions",
            },
        )

    def from_summary(self, state: ProjectState | dict[str, Any] | None) -> dict[str, Any]:
        if state is None:
            return {}
        if isinstance(state, ProjectState):
            return state.summary()
        return state.get("summary") or ProjectState(
            run_id=state.get("run_id"),
            project_id=state.get("project_id"),
            workspace_path=state.get("workspace_path", ""),
            actual_files=state.get("actual_files", {}),
            planned_files=state.get("planned_files", {}),
            merged_files=state.get("merged_files", {}),
            executor_actions=state.get("executor_actions", []),
            project_graph=state.get("project_graph", {}),
            execution_contract=state.get("execution_contract", {}),
            project_specification=state.get("project_specification", {}),
            decision_history=state.get("decision_history", []),
            validation_evidence=state.get("validation_evidence", {}),
            diagnostic_evidence=state.get("diagnostic_evidence", {}),
            state_source=state.get("state_source", {}),
        ).summary()

    def _actions(self, value: list[dict[str, Any]] | str | None) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return []
            value = parsed
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _actual_files(self, workspace: Path | None) -> dict[str, str]:
        if workspace is None or not workspace.exists():
            return {}
        files = {}
        for path in sorted(workspace.rglob("*")):
            if not self._is_context_file(workspace, path):
                continue
            relative = path.relative_to(workspace).as_posix()
            files[relative] = path.read_text(encoding="utf-8", errors="replace")
            if len(files) >= MAX_MERGED_FILES:
                break
        return files

    def _planned_files(self, actions: list[dict[str, Any]]) -> dict[str, str]:
        files = {}
        for action in actions:
            if action.get("action") != "write_file":
                continue
            path = action.get("path")
            if not self._safe_relative_path(path):
                continue
            content = action.get("content", "")
            files[path.replace("\\", "/")] = content if isinstance(content, str) else str(content)
        return files

    def _safe_relative_path(self, path: Any) -> bool:
        if not isinstance(path, str) or not path:
            return False
        normalized = path.replace("\\", "/")
        if PurePosixPath(normalized).is_absolute() or PureWindowsPath(path).is_absolute():
            return False
        return ".." not in PurePosixPath(normalized).parts

    def _file_section(self, files: dict[str, str], source: str) -> dict[str, Any]:
        return {
            "files": [
                ProjectStateFile(
                    path=path,
                    source="actual" if source == "filesystem" else "planned",
                    content_preview=content[:MAX_FILE_PREVIEW],
                    exists_on_disk=source == "filesystem",
                ).to_dict()
                for path, content in sorted(files.items())
            ],
            "count": len(files),
            "source": source,
        }

    def _merged_section(
        self,
        actual_files: dict[str, str],
        planned_files: dict[str, str],
    ) -> dict[str, Any]:
        paths = sorted(set(actual_files) | set(planned_files))
        files = []
        for path in paths:
            source = "actual" if path in actual_files else "planned"
            content = actual_files.get(path, planned_files.get(path, ""))
            files.append(
                ProjectStateFile(
                    path=path,
                    source=source,
                    content_preview=content[:MAX_FILE_PREVIEW],
                    exists_on_disk=path in actual_files,
                ).to_dict()
            )
        return {"files": files, "count": len(files), "source": "actual+planned"}

    def _materialize_files(self, workspace: Path, files: dict[str, str]) -> None:
        for relative, content in list(files.items())[:MAX_MERGED_FILES]:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _is_context_file(self, workspace: Path, path: Path) -> bool:
        if not path.is_file():
            return False
        relative = path.relative_to(workspace)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            return False
        return path.suffix.lower() in TEXT_SUFFIXES


def build_project_state(*args, **kwargs) -> ProjectState:
    return ProjectStateBuilder().build(*args, **kwargs)
