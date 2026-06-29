from pathlib import Path

from studio.core.project_knowledge import ProjectKnowledgeGraphBuilder

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "venv",
}

EXCLUDED_SUFFIXES = {
    ".bin",
    ".db",
    ".dll",
    ".exe",
    ".jpg",
    ".jpeg",
    ".log",
    ".png",
    ".pyc",
    ".pyo",
    ".so",
    ".sqlite",
    ".sqlite3",
}

DEPENDENCY_FILES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
}

METADATA_FILES = {"RUN.md", "README.md", "README.rst"}
MAX_TREE_ENTRIES = 250
MAX_SUMMARY_FILES = 80
MAX_FILE_BYTES = 64_000


class WorkspaceObserver:
    def observe(self, workspace_path: str | Path) -> dict:
        workspace = Path(workspace_path)
        if not workspace.exists():
            empty_graph = ProjectKnowledgeGraphBuilder().empty()
            return {
                "exists": False,
                "workspace_tree": [],
                "source_files": {"count": 0, "files": []},
                "tests": {"count": 0, "files": []},
                "dependency_files": [],
                "run_metadata_files": [],
                "ignored_files_summary": {"count": 0, "examples": []},
                "project_type_hints": [],
                "validation_artifacts": [],
                "project_graph": empty_graph,
            }

        tree: list[str] = []
        source_files: list[str] = []
        test_files: list[str] = []
        dependency_files: list[str] = []
        metadata_files: list[str] = []
        validation_artifacts: list[str] = []
        ignored_examples: list[str] = []
        ignored_count = 0

        for path in sorted(workspace.rglob("*")):
            relative = path.relative_to(workspace).as_posix()
            if self._is_excluded(path):
                ignored_count += 1
                if len(ignored_examples) < 10:
                    ignored_examples.append(relative)
                continue

            if len(tree) < MAX_TREE_ENTRIES:
                tree.append(relative + ("/" if path.is_dir() else ""))

            if not path.is_file() or self._is_large(path):
                continue

            if path.name in DEPENDENCY_FILES:
                dependency_files.append(relative)
            if path.name in METADATA_FILES:
                metadata_files.append(relative)
            if path.suffix == ".py":
                if relative.startswith("tests/") or path.name.startswith("test_"):
                    test_files.append(relative)
                else:
                    source_files.append(relative)
            if relative in {"pytest.ini", ".flake8"}:
                validation_artifacts.append(relative)

        project_graph = ProjectKnowledgeGraphBuilder().build(
            workspace=workspace,
            source_files=source_files[:MAX_SUMMARY_FILES],
            test_files=test_files[:MAX_SUMMARY_FILES],
            dependency_files=dependency_files[:MAX_SUMMARY_FILES],
            metadata_files=metadata_files[:MAX_SUMMARY_FILES],
            validation_artifacts=validation_artifacts[:MAX_SUMMARY_FILES],
        )

        return {
            "exists": True,
            "workspace_tree": tree,
            "source_files": {
                "count": len(source_files),
                "files": source_files[:MAX_SUMMARY_FILES],
            },
            "tests": {
                "count": len(test_files),
                "files": test_files[:MAX_SUMMARY_FILES],
            },
            "dependency_files": dependency_files[:MAX_SUMMARY_FILES],
            "run_metadata_files": metadata_files[:MAX_SUMMARY_FILES],
            "ignored_files_summary": {
                "count": ignored_count,
                "examples": ignored_examples,
            },
            "project_type_hints": project_graph["summary"]["project_types"],
            "validation_artifacts": validation_artifacts[:MAX_SUMMARY_FILES],
            "project_graph": project_graph,
        }

    def _is_large(self, path: Path) -> bool:
        try:
            return path.stat().st_size > MAX_FILE_BYTES
        except OSError:
            return True

    def _is_excluded(self, path: Path) -> bool:
        if any(part in EXCLUDED_DIRS for part in path.parts):
            return True
        return path.suffix.lower() in EXCLUDED_SUFFIXES

    def _project_type_hints(
        self,
        workspace: Path,
        source_files: list[str],
        dependency_files: list[str],
    ) -> list[str]:
        hints = []
        if source_files:
            hints.append("python")
        if "package.json" in dependency_files:
            hints.append("node")
        if "go.mod" in dependency_files:
            hints.append("go")

        for relative in source_files[:MAX_SUMMARY_FILES]:
            try:
                content = (workspace / relative).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "Flask(" in content or "@app.route" in content:
                hints.append("flask")
            if "FastAPI(" in content:
                hints.append("fastapi")
            if "django" in content.lower():
                hints.append("django")

        return sorted(set(hints))
