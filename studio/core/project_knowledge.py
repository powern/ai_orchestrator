import ast
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

MAX_TEXT_BYTES = 64_000


class ProjectKnowledgeGraphBuilder:
    def build(
        self,
        workspace: Path,
        source_files: list[str],
        test_files: list[str],
        dependency_files: list[str],
        metadata_files: list[str],
        validation_artifacts: list[str],
    ) -> dict[str, Any]:
        modules = [self._module_node(workspace, relative) for relative in source_files]
        tests = [self._test_node(workspace, relative) for relative in test_files]
        dependencies = self._dependencies(workspace, dependency_files)
        packages = self._packages(workspace)
        entrypoints = self._entrypoints(modules)
        routes = [route for module in modules for route in module["routes"]]
        imports = self._import_edges(modules)
        coverage = self._coverage_map(routes, modules, tests)
        documentation = self._documentation(metadata_files)
        runtime = self._runtime_graph(entrypoints, routes, validation_artifacts)
        project_types = self._project_types(modules, dependencies, dependency_files)

        graph = {
            "schema_version": 1,
            "project": {"type_hints": project_types},
            "packages": packages,
            "modules": modules,
            "entrypoints": entrypoints,
            "routes": routes,
            "dependencies": dependencies,
            "tests": tests,
            "import_graph": imports,
            "dependency_graph": self._dependency_edges(modules, dependencies),
            "runtime_graph": runtime,
            "test_coverage_map": coverage,
            "documentation_map": documentation,
            "validation_artifacts": validation_artifacts,
            "summary": self._summary(
                project_types,
                packages,
                modules,
                entrypoints,
                routes,
                dependencies,
                tests,
                coverage,
                documentation,
            ),
        }
        graph["nodes"] = self._nodes(graph)
        graph["edges"] = self._edges(graph)
        return graph

    def build_from_file_map(self, files: dict[str, str]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            for relative, content in files.items():
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            source_files = sorted(
                relative
                for relative in files
                if relative.endswith(".py")
                and not relative.startswith("tests/")
                and not Path(relative).name.startswith("test_")
            )
            test_files = sorted(
                relative
                for relative in files
                if relative.endswith(".py")
                and (relative.startswith("tests/") or Path(relative).name.startswith("test_"))
            )
            dependency_files = sorted(
                relative
                for relative in files
                if Path(relative).name
                in {
                    "requirements.txt",
                    "requirements-dev.txt",
                    "pyproject.toml",
                    "package.json",
                    "go.mod",
                    "Cargo.toml",
                }
            )
            metadata_files = sorted(
                relative
                for relative in files
                if Path(relative).name in {"RUN.md", "README.md", "README.rst"}
            )
            validation_artifacts = sorted(
                relative for relative in files if relative in {"pytest.ini", ".flake8"}
            )
            return self.build(
                workspace=workspace,
                source_files=source_files,
                test_files=test_files,
                dependency_files=dependency_files,
                metadata_files=metadata_files,
                validation_artifacts=validation_artifacts,
            )

    def empty(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project": {"type_hints": []},
            "packages": [],
            "modules": [],
            "entrypoints": [],
            "routes": [],
            "dependencies": [],
            "tests": [],
            "import_graph": [],
            "dependency_graph": [],
            "runtime_graph": [],
            "test_coverage_map": {"routes": [], "modules": []},
            "documentation_map": [],
            "validation_artifacts": [],
            "summary": {
                "project_types": [],
                "package_count": 0,
                "module_count": 0,
                "entrypoint_count": 0,
                "route_count": 0,
                "dependency_count": 0,
                "test_count": 0,
                "document_count": 0,
                "covered_routes": 0,
                "uncovered_routes": 0,
            },
            "nodes": [],
            "edges": [],
        }

    def _module_node(self, workspace: Path, relative: str) -> dict[str, Any]:
        content = self._read_text(workspace / relative)
        tree = self._parse_ast(content)
        imports = self._imports(tree) if tree else []
        functions = self._functions(tree) if tree else []
        classes = self._classes(tree) if tree else []
        routes = self._routes(tree, relative) if tree else []
        entrypoint = self._has_main_guard(tree) if tree else False
        framework = self._framework(content, routes)

        return {
            "id": f"module:{self._module_name(relative)}",
            "type": "Module",
            "path": relative,
            "name": self._module_name(relative),
            "imports": imports,
            "functions": functions,
            "classes": classes,
            "routes": routes,
            "framework": framework,
            "is_entrypoint": entrypoint,
            "starts_runtime": entrypoint and self._starts_runtime(content),
            "uses_cli": self._uses_cli(content, tree),
        }

    def _test_node(self, workspace: Path, relative: str) -> dict[str, Any]:
        content = self._read_text(workspace / relative)
        tree = self._parse_ast(content)
        test_cases = []
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    test_cases.append(node.name)
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                            test_cases.append(f"{node.name}.{item.name}")
        return {
            "id": f"test:{relative}",
            "type": "TestSuite",
            "path": relative,
            "test_cases": sorted(test_cases),
            "imports": self._imports(tree) if tree else [],
            "mentions": self._mentions(content),
        }

    def _dependencies(self, workspace: Path, dependency_files: list[str]) -> list[dict]:
        dependencies = []
        for relative in dependency_files:
            path = workspace / relative
            if path.name.startswith("requirements") and path.suffix == ".txt":
                dependencies.extend(self._requirements_dependencies(path))
            elif path.name == "pyproject.toml":
                dependencies.extend(self._pyproject_dependencies(path))
            elif path.name == "package.json":
                dependencies.append({"name": "node-project", "source": relative})
            elif path.name == "go.mod":
                dependencies.append({"name": "go-module", "source": relative})
        return sorted(dependencies, key=lambda item: (item["source"], item["name"].lower()))

    def _requirements_dependencies(self, path: Path) -> list[dict]:
        items = []
        for line in self._read_text(path).splitlines():
            value = line.strip()
            if not value or value.startswith("#") or value.startswith("-"):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)\s*([<>=!~].*)?$", value)
            if match:
                items.append(
                    {
                        "type": "Dependency",
                        "name": match.group(1),
                        "constraint": (match.group(2) or "").strip(),
                        "source": path.name,
                    }
                )
        return items

    def _pyproject_dependencies(self, path: Path) -> list[dict]:
        try:
            data = tomllib.loads(self._read_text(path))
        except tomllib.TOMLDecodeError:
            return []
        dependencies = []
        for value in data.get("project", {}).get("dependencies", []):
            match = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)$", value)
            if match:
                dependencies.append(
                    {
                        "type": "Dependency",
                        "name": match.group(1),
                        "constraint": match.group(2).strip(),
                        "source": path.name,
                    }
                )
        return dependencies

    def _packages(self, workspace: Path) -> list[dict]:
        packages = []
        for path in sorted(workspace.rglob("__init__.py")):
            if self._is_hidden_or_cache(path):
                continue
            relative = path.parent.relative_to(workspace).as_posix()
            packages.append(
                {
                    "id": f"package:{relative.replace('/', '.')}",
                    "type": "Package",
                    "path": relative,
                    "name": relative.replace("/", "."),
                }
            )
        return packages

    def _entrypoints(self, modules: list[dict]) -> list[dict]:
        entrypoints = []
        for module in modules:
            if module["is_entrypoint"] or module["starts_runtime"] or module["uses_cli"]:
                kind = "cli" if module["uses_cli"] else "web" if module["routes"] else "python"
                entrypoints.append(
                    {
                        "id": f"entrypoint:{module['name']}",
                        "type": "EntryPoint",
                        "module": module["name"],
                        "path": module["path"],
                        "kind": kind,
                        "starts_runtime": module["starts_runtime"],
                    }
                )
        return entrypoints

    def _import_edges(self, modules: list[dict]) -> list[dict]:
        module_names = {module["name"] for module in modules}
        roots = {name.split(".")[0] for name in module_names}
        edges = []
        for module in modules:
            for imported in module["imports"]:
                target = self._resolve_internal_import(imported, module_names, roots)
                if target:
                    edges.append(
                        {
                            "source": module["name"],
                            "target": target,
                            "relationship": "imports",
                        }
                    )
        return edges

    def _dependency_edges(self, modules: list[dict], dependencies: list[dict]) -> list[dict]:
        dependency_names = {
            dependency["name"].lower(): dependency["name"] for dependency in dependencies
        }
        edges = []
        for module in modules:
            for imported in module["imports"]:
                root = imported.split(".")[0].replace("_", "-").lower()
                if root in dependency_names:
                    edges.append(
                        {
                            "source": module["name"],
                            "target": dependency_names[root],
                            "relationship": "requires",
                        }
                    )
        return edges

    def _runtime_graph(
        self,
        entrypoints: list[dict],
        routes: list[dict],
        artifacts: list[str],
    ) -> list[dict]:
        graph = []
        for entrypoint in entrypoints:
            graph.append(
                {
                    "source": entrypoint["id"],
                    "target": "project",
                    "relationship": "starts",
                }
            )
            for route in routes:
                if route["module"] == entrypoint["module"]:
                    graph.append(
                        {
                            "source": route["id"],
                            "target": entrypoint["id"],
                            "relationship": "belongs_to",
                        }
                    )
        for artifact in artifacts:
            graph.append(
                {
                    "source": f"validation:{artifact}",
                    "target": "project",
                    "relationship": "validates",
                }
            )
        return graph

    def _coverage_map(
        self,
        routes: list[dict],
        modules: list[dict],
        tests: list[dict],
    ) -> dict[str, list[dict]]:
        route_coverage = []
        module_coverage = []
        for route in routes:
            covering_tests = [
                test["path"] for test in tests if route["path"] in test["mentions"]
            ]
            route_coverage.append(
                {
                    "route": route["id"],
                    "path": route["path"],
                    "covered_by": covering_tests,
                    "covered": bool(covering_tests),
                }
            )
        for module in modules:
            covering_tests = [
                test["path"]
                for test in tests
                if module["name"] in test["imports"] or module["name"] in test["mentions"]
            ]
            module_coverage.append(
                {
                    "module": module["name"],
                    "covered_by": covering_tests,
                    "covered": bool(covering_tests),
                }
            )
        return {"routes": route_coverage, "modules": module_coverage}

    def _documentation(self, metadata_files: list[str]) -> list[dict]:
        return [
            {
                "id": f"doc:{relative}",
                "type": "Documentation",
                "path": relative,
                "describes": "runtime" if relative.upper().startswith("RUN") else "project",
            }
            for relative in metadata_files
        ]

    def _nodes(self, graph: dict) -> list[dict]:
        nodes = [{"id": "project", "type": "Project", "label": "Project"}]
        nodes.extend(graph["packages"])
        nodes.extend(graph["modules"])
        nodes.extend(graph["entrypoints"])
        nodes.extend(graph["routes"])
        nodes.extend(graph["dependencies"])
        nodes.extend(graph["tests"])
        nodes.extend(graph["documentation_map"])
        return nodes

    def _edges(self, graph: dict) -> list[dict]:
        edges = []
        edges.extend(graph["import_graph"])
        edges.extend(graph["dependency_graph"])
        edges.extend(graph["runtime_graph"])
        for item in graph["test_coverage_map"]["routes"]:
            for test_path in item["covered_by"]:
                edges.append(
                    {
                        "source": f"test:{test_path}",
                        "target": item["route"],
                        "relationship": "validates",
                    }
                )
        return edges

    def _summary(
        self,
        project_types: list[str],
        packages: list[dict],
        modules: list[dict],
        entrypoints: list[dict],
        routes: list[dict],
        dependencies: list[dict],
        tests: list[dict],
        coverage: dict,
        documentation: list[dict],
    ) -> dict:
        covered_routes = sum(1 for item in coverage["routes"] if item["covered"])
        return {
            "project_types": project_types,
            "package_count": len(packages),
            "module_count": len(modules),
            "entrypoint_count": len(entrypoints),
            "route_count": len(routes),
            "dependency_count": len(dependencies),
            "test_count": len(tests),
            "document_count": len(documentation),
            "covered_routes": covered_routes,
            "uncovered_routes": len(routes) - covered_routes,
        }

    def _project_types(
        self,
        modules: list[dict],
        dependencies: list[dict],
        dependency_files: list[str],
    ) -> list[str]:
        hints = []
        if modules:
            hints.append("python")
        if any(module["framework"] == "flask" for module in modules):
            hints.append("flask")
        if any(module["framework"] == "fastapi" for module in modules):
            hints.append("fastapi")
        if any(module["uses_cli"] for module in modules):
            hints.append("cli")
        if "package.json" in dependency_files:
            hints.append("node")
        if "go.mod" in dependency_files:
            hints.append("go")
        dependency_names = {dependency["name"].lower() for dependency in dependencies}
        if "django" in dependency_names:
            hints.append("django")
        return sorted(set(hints))

    def _routes(self, tree: ast.AST, relative: str) -> list[dict]:
        routes = []
        module_name = self._module_name(relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                route = self._route_from_decorator(decorator)
                if route:
                    route.update(
                        {
                            "id": f"route:{module_name}:{route['path']}:{node.name}",
                            "type": "Route",
                            "module": module_name,
                            "handler": node.name,
                        }
                    )
                    routes.append(route)
        return routes

    def _route_from_decorator(self, decorator: ast.AST) -> dict | None:
        if not isinstance(decorator, ast.Call):
            return None
        name = self._call_name(decorator.func)
        route_methods = {"get", "post", "put", "patch", "delete", "route"}
        if not name or name.split(".")[-1] not in route_methods:
            return None
        path = self._literal_arg(decorator.args[0]) if decorator.args else None
        if not path:
            return None
        methods = []
        if name.endswith(".route"):
            for keyword in decorator.keywords:
                if keyword.arg == "methods":
                    methods = self._literal_list(keyword.value)
        if not methods:
            method = name.split(".")[-1]
            methods = ["GET"] if method == "route" else [method.upper()]
        framework = "fastapi" if name.split(".")[-1] != "route" else "flask"
        return {"path": path, "methods": methods, "framework": framework}

    def _imports(self, tree: ast.AST | None) -> list[str]:
        if tree is None:
            return []
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return sorted(set(imports))

    def _functions(self, tree: ast.AST) -> list[str]:
        return sorted(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )

    def _classes(self, tree: ast.AST) -> list[str]:
        return sorted(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))

    def _has_main_guard(self, tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
                return True
        return False

    def _uses_cli(self, content: str, tree: ast.AST | None) -> bool:
        imports = self._imports(tree)
        return (
            "argparse" in imports
            or "click" in imports
            or "@click.command" in content
            or "ArgumentParser(" in content
        )

    def _starts_runtime(self, content: str) -> bool:
        return "app.run(" in content or "uvicorn.run(" in content or "main()" in content

    def _framework(self, content: str, routes: list[dict]) -> str | None:
        if "FastAPI(" in content or any(route["framework"] == "fastapi" for route in routes):
            return "fastapi"
        if "Flask(" in content or any(route["framework"] == "flask" for route in routes):
            return "flask"
        if "django" in content.lower():
            return "django"
        return None

    def _resolve_internal_import(
        self,
        imported: str,
        module_names: set[str],
        roots: set[str],
    ) -> str | None:
        if imported in module_names:
            return imported
        for module_name in module_names:
            if module_name.startswith(f"{imported}."):
                return module_name
        if imported.split(".")[0] in roots:
            return imported
        return None

    def _module_name(self, relative: str) -> str:
        if relative.endswith("/__init__.py"):
            return relative[: -len("/__init__.py")].replace("/", ".")
        return relative.removesuffix(".py").replace("/", ".")

    def _read_text(self, path: Path) -> str:
        try:
            if path.stat().st_size > MAX_TEXT_BYTES:
                return ""
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _parse_ast(self, content: str) -> ast.AST | None:
        try:
            return ast.parse(content)
        except SyntaxError:
            return None

    def _call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._call_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    def _literal_arg(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def _literal_list(self, node: ast.AST) -> list[str]:
        if not isinstance(node, ast.List | ast.Tuple):
            return []
        values = [self._literal_arg(item) for item in node.elts]
        return [value.upper() for value in values if value]

    def _mentions(self, content: str) -> list[str]:
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_./-]*", content))
        quoted_paths = set(re.findall(r"['\"](/[A-Za-z0-9_./-]*)['\"]", content))
        return sorted(words | quoted_paths)

    def _is_hidden_or_cache(self, path: Path) -> bool:
        excluded = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
        return any(part in excluded for part in path.parts)
