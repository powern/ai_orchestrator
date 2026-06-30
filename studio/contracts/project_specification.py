import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeSpecification:
    kind: str = "unknown"
    host: str | None = None
    port: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "host": self.host, "port": self.port}


@dataclass(frozen=True)
class FeatureSpecification:
    name: str
    kind: str = "general"
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "required": self.required}


@dataclass(frozen=True)
class EntitySpecification:
    name: str
    fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "fields": self.fields}


@dataclass(frozen=True)
class ProjectSpecification:
    schema_version: int = 1
    project_type: str = "unknown"
    language: str = "unknown"
    framework: str = "unknown"
    runtime: RuntimeSpecification = field(default_factory=RuntimeSpecification)
    features: list[FeatureSpecification] = field(default_factory=list)
    entities: list[EntitySpecification] = field(default_factory=list)
    routes_or_commands: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    expected_tests: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_type": self.project_type,
            "language": self.language,
            "framework": self.framework,
            "runtime": self.runtime.to_dict(),
            "features": [feature.to_dict() for feature in self.features],
            "entities": [entity.to_dict() for entity in self.entities],
            "routes_or_commands": self.routes_or_commands,
            "dependencies": self.dependencies,
            "expected_files": self.expected_files,
            "expected_tests": self.expected_tests,
            "acceptance_criteria": self.acceptance_criteria,
            "constraints": self.constraints,
            "out_of_scope": self.out_of_scope,
            "confidence": self.confidence,
            "source_evidence": self.source_evidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ProjectSpecification":
        value = value or {}
        runtime = value.get("runtime") or {}
        return cls(
            schema_version=value.get("schema_version", 1),
            project_type=value.get("project_type", "unknown"),
            language=value.get("language", "unknown"),
            framework=value.get("framework", "unknown"),
            runtime=RuntimeSpecification(
                kind=runtime.get("kind", "unknown"),
                host=runtime.get("host"),
                port=runtime.get("port"),
            ),
            features=[
                FeatureSpecification(**feature) for feature in value.get("features", [])
            ],
            entities=[EntitySpecification(**entity) for entity in value.get("entities", [])],
            routes_or_commands=list(value.get("routes_or_commands", [])),
            dependencies=list(value.get("dependencies", [])),
            expected_files=list(value.get("expected_files", [])),
            expected_tests=list(value.get("expected_tests", [])),
            acceptance_criteria=list(value.get("acceptance_criteria", [])),
            constraints=list(value.get("constraints", [])),
            out_of_scope=list(value.get("out_of_scope", [])),
            confidence=float(value.get("confidence", 0.0)),
            source_evidence=list(value.get("source_evidence", [])),
        )


class ProjectSpecificationEngine:
    def extract(self, request_text: str | None) -> ProjectSpecification:
        text = request_text or ""
        lowered = text.lower()
        evidence: list[str] = []
        language = "unknown"
        framework = "unknown"
        project_type = "unknown"
        runtime = RuntimeSpecification()
        dependencies: list[str] = []

        if "flask" in lowered:
            language = "python"
            framework = "flask"
            project_type = "web_app"
            runtime = RuntimeSpecification(kind="web", host="0.0.0.0", port=5000)
            dependencies.append("flask")
            evidence.append("Detected explicit Flask framework request.")
        elif "fastapi" in lowered:
            language = "python"
            framework = "fastapi"
            project_type = "api"
            runtime = RuntimeSpecification(kind="web", host="0.0.0.0", port=8000)
            dependencies.append("fastapi")
            evidence.append("Detected explicit FastAPI framework request.")
        elif "asp.net" in lowered or ".net" in lowered or "c#" in lowered:
            language = "csharp"
            framework = "aspnet" if "asp.net" in lowered else "unknown"
            project_type = "web_app" if "asp.net" in lowered else "unknown"
            evidence.append("Detected .NET/C# request.")
        elif "c++" in lowered or "cmake" in lowered:
            language = "cpp"
            framework = "none"
            evidence.append("Detected C++/CMake request.")
        elif "react" in lowered or "node" in lowered or "express" in lowered:
            language = "node"
            if "react" in lowered:
                framework = "react"
            elif "express" in lowered:
                framework = "express"
            else:
                framework = "unknown"
            project_type = "web_app" if "react" in lowered else "api"
            evidence.append("Detected Node ecosystem request.")

        if "cli" in lowered or "command line" in lowered:
            project_type = "cli"
            runtime = RuntimeSpecification(kind="cli")
            evidence.append("Detected CLI runtime request.")
        elif project_type == "unknown" and "api" in lowered:
            project_type = "api"
            runtime = RuntimeSpecification(kind="web")
            evidence.append("Detected API project type request.")

        features = self._features(lowered)
        entities = self._entities(lowered)
        acceptance = self._acceptance_criteria(text)
        expected_tests = [feature.name for feature in features if feature.required]
        confidence = self._confidence(language, framework, project_type, features, evidence)

        return ProjectSpecification(
            project_type=project_type,
            language=language,
            framework=framework,
            runtime=runtime,
            features=features,
            entities=entities,
            dependencies=sorted(set(dependencies)),
            expected_files=self._expected_files(language, framework),
            expected_tests=expected_tests,
            acceptance_criteria=acceptance,
            constraints=self._constraints(text),
            confidence=confidence,
            source_evidence=evidence,
        )

    def _features(self, lowered: str) -> list[FeatureSpecification]:
        features = []
        mapping = {
            "create": "crud_create",
            "add": "crud_create",
            "edit": "crud_update",
            "update": "crud_update",
            "delete": "crud_delete",
            "remove": "crud_delete",
            "view": "crud_read",
            "list": "crud_list",
        }
        for word, kind in mapping.items():
            if word in lowered:
                features.append(FeatureSpecification(name=f"{word} item", kind=kind))
        if "counter" in lowered:
            features.append(FeatureSpecification(name="counter", kind="stateful_ui"))
        return features

    def _entities(self, lowered: str) -> list[EntitySpecification]:
        entities = []
        if "note" in lowered:
            fields = ["title", "text"]
            if "date" in lowered or "created" in lowered:
                fields.append("created_date")
            entities.append(EntitySpecification(name="note", fields=fields))
        return entities

    def _acceptance_criteria(self, text: str) -> list[str]:
        markers = ("must", "should", "all tests", "pass", "raise", "return", "show")
        return [
            line.strip("-* ")
            for line in text.splitlines()
            if any(marker in line.lower() for marker in markers)
        ]

    def _constraints(self, text: str) -> list[str]:
        return [
            line.strip("-* ")
            for line in text.splitlines()
            if "only" in line.lower() or "must not" in line.lower()
        ]

    def _expected_files(self, language: str, framework: str) -> list[str]:
        if language == "python":
            files = ["app/__init__.py", "app/main.py", "tests/test_main.py"]
            if framework in {"flask", "fastapi"}:
                files.extend(["requirements.txt", "RUN.md"])
            return files
        if language == "csharp":
            return ["*.csproj"]
        if language == "cpp":
            return ["CMakeLists.txt", "src/main.cpp"]
        return []

    def _confidence(
        self,
        language: str,
        framework: str,
        project_type: str,
        features: list[FeatureSpecification],
        evidence: list[str],
    ) -> float:
        score = 0.15
        if language != "unknown":
            score += 0.25
        if framework != "unknown":
            score += 0.2
        if project_type != "unknown":
            score += 0.15
        if features:
            score += 0.1
        if evidence:
            score += 0.1
        return round(min(score, 0.95), 2)


def build_project_specification(request_text: str | None) -> ProjectSpecification:
    return ProjectSpecificationEngine().extract(request_text)
