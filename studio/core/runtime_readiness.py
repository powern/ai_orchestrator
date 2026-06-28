import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RuntimeReadinessReport:
    dependency_check: str
    dependency_installation: str
    runtime_entrypoint: str
    runtime_smoke: str
    behavior_tests: str
    metadata: str
    manual_run_ready: bool
    entrypoint_command: str | None = None
    expected_url: str | None = None
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dependency_check": self.dependency_check,
            "dependency_installation": self.dependency_installation,
            "runtime_entrypoint": self.runtime_entrypoint,
            "runtime_smoke": self.runtime_smoke,
            "behavior_tests": self.behavior_tests,
            "metadata": self.metadata,
            "manual_run_ready": self.manual_run_ready,
            "entrypoint_command": self.entrypoint_command,
            "expected_url": self.expected_url,
            "findings": self.findings,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class RuntimeReadinessValidator:
    def validate(self, workspace_path: str | Path) -> RuntimeReadinessReport:
        workspace = Path(workspace_path)
        findings: list[str] = []
        requirements = self._read_requirements(workspace)
        python_files = list(self._python_files(workspace))
        entrypoint = self._entrypoint(workspace)
        is_web_app = self._looks_like_web_app(python_files)

        dependency_findings = self._dependency_findings(requirements, python_files)
        findings.extend(dependency_findings)

        entrypoint_status = "passed"
        entrypoint_command = None
        if entrypoint is None and (is_web_app or python_files):
            entrypoint_status = "failed"
            findings.append("Runtime entrypoint is missing.")
        elif entrypoint is not None:
            entrypoint_command = f"python {entrypoint.relative_to(workspace).as_posix()}"

        smoke_status = "skipped"
        if entrypoint is not None:
            smoke_status = self._runtime_smoke(workspace, entrypoint, findings)

        behavior_status = self._behavior_tests(workspace, is_web_app, findings)
        metadata_status = self._metadata(workspace, is_web_app, findings)

        dependency_status = "failed" if dependency_findings else "passed"
        installation_status = "failed" if dependency_findings else "passed"
        manual_run_ready = not findings

        return RuntimeReadinessReport(
            dependency_check=dependency_status,
            dependency_installation=installation_status,
            runtime_entrypoint=entrypoint_status,
            runtime_smoke=smoke_status,
            behavior_tests=behavior_status,
            metadata=metadata_status,
            manual_run_ready=manual_run_ready,
            entrypoint_command=entrypoint_command,
            expected_url="http://127.0.0.1:5000/" if is_web_app else None,
            findings=findings,
        )

    def _python_files(self, workspace: Path):
        for root in ("app", "."):
            base = workspace / root
            if not base.exists():
                continue
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" not in path.parts:
                    yield path

    def _read_requirements(self, workspace: Path) -> dict[str, str | None]:
        path = workspace / "requirements.txt"
        if not path.exists():
            return {}

        requirements = {}
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)(?:==([^;\s]+))?", line)
            if match:
                requirements[match.group(1).lower()] = match.group(2)

        return requirements

    def _dependency_findings(
        self,
        requirements: dict[str, str | None],
        python_files: list[Path],
    ) -> list[str]:
        findings = []
        imports = self._imports(python_files)

        if "flask" in imports and "flask" not in requirements:
            findings.append("Flask is imported but missing from requirements.txt.")

        flask_version = requirements.get("flask")
        werkzeug_version = requirements.get("werkzeug")
        if flask_version and self._version_lt(flask_version, "2.2"):
            if werkzeug_version is None:
                findings.append(
                    "Flask < 2.2 requires a compatible Werkzeug pin; Werkzeug 3.x is incompatible."
                )
            elif self._version_ge(werkzeug_version, "3.0"):
                findings.append("Flask < 2.2 is incompatible with Werkzeug >= 3.0.")

        return findings

    def _imports(self, python_files: list[Path]) -> set[str]:
        imports = set()
        pattern = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+|import\s+([\w.]+))")
        for path in python_files:
            content = path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                match = pattern.match(line)
                if match:
                    imports.add((match.group(1) or match.group(2)).split(".")[0].lower())
        return imports

    def _entrypoint(self, workspace: Path) -> Path | None:
        for relative in ("app/main.py", "app.py", "main.py"):
            path = workspace / relative
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            if 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content:
                return path
        return None

    def _runtime_smoke(self, workspace: Path, entrypoint: Path, findings: list[str]) -> str:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace)
        try:
            result = subprocess.run(
                [sys.executable, str(entrypoint)],
                cwd=workspace,
                env=env,
                text=True,
                capture_output=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            return "passed"

        if result.returncode != 0:
            findings.append(
                "Runtime smoke failed: "
                + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
            )
            return "failed"

        return "passed"

    def _behavior_tests(self, workspace: Path, is_web_app: bool, findings: list[str]) -> str:
        if not is_web_app:
            return "skipped"

        test_content = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in sorted((workspace / "tests").glob("test*.py"))
        )
        expected = ("Visual Smoke Test", "Counter: 0", "Counter: 1", "Increase", "Reset")
        missing = [item for item in expected if item not in test_content]
        if missing:
            findings.append("Behavior tests are missing visible assertions: " + ", ".join(missing))
            return "failed"

        return "passed"

    def _metadata(self, workspace: Path, is_web_app: bool, findings: list[str]) -> str:
        metadata = None
        for filename in ("RUN.md", "README.md"):
            path = workspace / filename
            if path.exists():
                metadata = path.read_text(encoding="utf-8", errors="replace")
                break

        if metadata is None:
            findings.append("Run metadata file RUN.md or README.md is missing.")
            return "failed"

        required = ["install", "run", "test"]
        if is_web_app:
            required.append("http://127.0.0.1:5000")

        missing = [item for item in required if item.lower() not in metadata.lower()]
        if missing:
            findings.append("Run metadata is missing: " + ", ".join(missing))
            return "failed"

        return "passed"

    def _looks_like_web_app(self, python_files: list[Path]) -> bool:
        for path in python_files:
            content = path.read_text(encoding="utf-8", errors="replace")
            if "Flask(" in content or "@app.route" in content:
                return True
        return False

    def _version_lt(self, version: str, expected: str) -> bool:
        return self._version_tuple(version) < self._version_tuple(expected)

    def _version_ge(self, version: str, expected: str) -> bool:
        return self._version_tuple(version) >= self._version_tuple(expected)

    def _version_tuple(self, version: str) -> tuple[int, ...]:
        parts = []
        for part in re.split(r"[.\-]", version):
            if not part.isdigit():
                break
            parts.append(int(part))
        return tuple(parts or [0])
