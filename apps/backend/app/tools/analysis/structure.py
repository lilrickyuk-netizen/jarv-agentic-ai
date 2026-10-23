"""
JARV Backend - Structure Analysis Tools

Tools for analyzing dependencies, imports, architecture, and performance.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import ast
import json
import logging
from pathlib import Path
import re
import tomllib

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== ANALYZE DEPENDENCIES TOOL =====

class AnalyzeDependenciesInput(BaseModel):
    """Input schema for dependency analysis"""
    path: str = Field(..., description="Path to project or dependency file")
    include_dev: bool = Field(default=False, description="Include dev dependencies")
    check_outdated: bool = Field(default=True, description="Check for outdated packages")
    check_security: bool = Field(default=True, description="Check for vulnerabilities")


class Dependency(BaseModel):
    """Dependency information"""
    name: str
    current_version: str
    latest_version: Optional[str] = None
    is_outdated: Optional[bool] = None
    vulnerabilities: Optional[int] = None
    license: Optional[str] = None


class AnalyzeDependenciesOutput(BaseModel):
    """Output schema for dependency analysis"""
    path: str
    total_dependencies: int
    direct_dependencies: int
    transitive_dependencies: Optional[int] = None
    outdated_count: Optional[int] = None
    vulnerable_count: Optional[int] = None
    dependencies: List[Dependency]
    checks_performed: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class AnalyzeDependenciesTool(ToolBase):
    """Tool for analyzing project dependencies"""

    @property
    def name(self) -> str:
        return "analyze_dependencies"

    @property
    def description(self) -> str:
        return "Analyze project dependencies, check for outdated packages and vulnerabilities."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeDependenciesInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeDependenciesOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "analysis"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Analyze dependencies"""
        path = input_data["path"]
        include_dev = input_data.get("include_dev", False)
        check_outdated = input_data.get("check_outdated", True)
        check_security = input_data.get("check_security", True)

        try:
            logger.info(f"Analyzing dependencies: {path}")
            target = Path(path)
            if target.is_dir():
                candidates = [target / name for name in (
                    "pyproject.toml", "requirements.txt", "package.json", "Cargo.toml")]
                target = next((candidate for candidate in candidates if candidate.is_file()), None)
                if target is None:
                    return self.create_result(
                        success=False,
                        error_message="No supported dependency manifest found in the project directory.",
                    )
            if target is None or not target.is_file():
                return self.create_result(success=False, error_message=f"Manifest not found: {path}")

            raw_dependencies = []
            if target.name == "pyproject.toml":
                document = tomllib.loads(target.read_text(encoding="utf-8"))
                project = document.get("project", {})
                raw_dependencies.extend(project.get("dependencies", []) or [])
                if include_dev:
                    optional = project.get("optional-dependencies", {}) or {}
                    for group in optional.values():
                        raw_dependencies.extend(group or [])
                poetry = document.get("tool", {}).get("poetry", {})
                for name, version in (poetry.get("dependencies", {}) or {}).items():
                    if name.lower() != "python":
                        raw_dependencies.append({"name": name, "version": version})
                if include_dev:
                    for group in (poetry.get("group", {}) or {}).values():
                        raw_dependencies.extend(
                            {"name": name, "version": value}
                            for name, value in (group.get("dependencies", {}) or {}).items()
                        )
            elif target.name == "requirements.txt":
                raw_dependencies.extend(target.read_text(encoding="utf-8").splitlines())
            elif target.name == "package.json":
                manifest = json.loads(target.read_text(encoding="utf-8"))
                raw_dependencies.extend(
                    {"name": name, "version": version}
                    for name, version in (manifest.get("dependencies", {}) or {}).items()
                )
                if include_dev:
                    raw_dependencies.extend(
                        {"name": name, "version": version}
                        for name, version in (manifest.get("devDependencies", {}) or {}).items()
                    )
            elif target.name == "Cargo.toml":
                manifest = tomllib.loads(target.read_text(encoding="utf-8"))
                raw_dependencies.extend(
                    {"name": name, "version": version}
                    for name, version in (manifest.get("dependencies", {}) or {}).items()
                )
                if include_dev:
                    raw_dependencies.extend(
                        {"name": name, "version": version}
                        for name, version in (manifest.get("dev-dependencies", {}) or {}).items()
                    )
            else:
                return self.create_result(
                    success=False, error_message=f"Unsupported dependency manifest: {target.name}")

            dependencies = []
            for item in raw_dependencies:
                if isinstance(item, str):
                    spec = item.split(";", 1)[0].strip()
                    if not spec or spec.startswith(("#", "-")):
                        continue
                    match = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", spec)
                    if not match:
                        continue
                    name, version = match.groups()
                else:
                    name = str(item.get("name", "")).strip()
                    version_value = item.get("version", "unspecified")
                    version = (str(version_value.get("version", "unspecified"))
                               if isinstance(version_value, dict) else str(version_value))
                if name:
                    dependencies.append({
                        "name": name,
                        "current_version": version.strip() or "unspecified",
                        "latest_version": None,
                        "is_outdated": None,
                        "vulnerabilities": None,
                        "license": None,
                    })

            limitations = []
            if check_outdated:
                limitations.append("Outdated checks require a package registry; none was queried.")
            if check_security:
                limitations.append("Dependency vulnerability checks require an advisory database; none was queried.")
            limitations.append("Only direct manifest dependencies were parsed; transitive dependencies are not inferred.")

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "total_dependencies": len(dependencies),
                    "direct_dependencies": len(dependencies),
                    "transitive_dependencies": None,
                    "outdated_count": None,
                    "vulnerable_count": None,
                    "dependencies": dependencies,
                    "checks_performed": ["manifest_parse"],
                    "limitations": limitations,
                },
                output_text=(f"Dependencies: {len(dependencies)} direct entries parsed from {target.name}; "
                             "registry and vulnerability checks not performed."),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze dependencies: {str(e)}",
            )


# ===== ANALYZE IMPORTS TOOL =====

class AnalyzeImportsInput(BaseModel):
    """Input schema for import analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    find_circular: bool = Field(default=True, description="Find circular imports")
    find_unused: bool = Field(default=True, description="Find unused imports")


class ImportIssue(BaseModel):
    """Import issue"""
    type: str = Field(..., description="Type: circular, unused, missing")
    file: str
    line: int
    import_name: str
    description: str


class AnalyzeImportsOutput(BaseModel):
    """Output schema for import analysis"""
    path: str
    total_imports: int
    circular_imports: int
    unused_imports: int
    missing_imports: Optional[int] = None
    issues: List[ImportIssue]
    limitations: List[str] = Field(default_factory=list)


class AnalyzeImportsTool(ToolBase):
    """Tool for analyzing import structure"""

    @property
    def name(self) -> str:
        return "analyze_imports"

    @property
    def description(self) -> str:
        return "Analyze import statements, find circular dependencies and unused imports."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeImportsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeImportsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "analysis"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Analyze imports"""
        path = input_data["path"]
        find_circular = input_data.get("find_circular", True)
        find_unused = input_data.get("find_unused", True)

        try:
            logger.info(f"Analyzing imports: {path}")
            root = Path(path)
            if not root.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            source_root = root if root.is_dir() else root.parent
            files = [root] if root.is_file() else sorted(root.rglob("*.py"))
            files = [candidate for candidate in files if candidate.suffix == ".py"]
            if not files:
                return self.create_result(
                    success=False,
                    error_message="Import analysis supports Python source files only; none were found.",
                )

            module_by_file = {}
            file_by_module = {}
            for source_file in files:
                relative = source_file.relative_to(source_root).with_suffix("")
                module = ".".join(relative.parts)
                if module.endswith(".__init__"):
                    module = module[:-9]
                module_by_file[source_file] = module
                file_by_module[module] = source_file

            import_count = 0
            issues = []
            graph = {module: [] for module in file_by_module}
            for source_file in files:
                source = source_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(source_file))
                names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
                current_module = module_by_file[source_file]
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        import_count += 1
                        for alias in node.names:
                            bound_name = alias.asname or alias.name.split(".")[0]
                            target_module = alias.name
                            if find_unused and bound_name not in names:
                                issues.append({
                                    "type": "unused", "file": str(source_file),
                                    "line": node.lineno, "import_name": bound_name,
                                    "description": f"Imported name '{bound_name}' is not referenced.",
                                })
                            if target_module in file_by_module:
                                graph[current_module].append((target_module, node.lineno))
                    elif isinstance(node, ast.ImportFrom):
                        import_count += 1
                        target_module = node.module or ""
                        if node.level:
                            package_parts = current_module.split(".")[:-node.level]
                            target_module = ".".join(package_parts + ([target_module] if target_module else []))
                        for alias in node.names:
                            bound_name = alias.asname or alias.name
                            if find_unused and bound_name not in names:
                                issues.append({
                                    "type": "unused", "file": str(source_file),
                                    "line": node.lineno, "import_name": bound_name,
                                    "description": f"Imported name '{bound_name}' is not referenced.",
                                })
                        if target_module in file_by_module:
                            graph[current_module].append((target_module, node.lineno))

            cycles = set()
            if find_circular:
                visited = set()
                stack = []
                stack_positions = {}

                def visit(module):
                    if module in stack_positions:
                        cycles.add(frozenset(stack[stack_positions[module]:]))
                        return
                    if module in visited:
                        return
                    stack_positions[module] = len(stack)
                    stack.append(module)
                    for dependency, _ in graph[module]:
                        visit(dependency)
                    stack.pop()
                    stack_positions.pop(module, None)
                    visited.add(module)

                for module in graph:
                    visit(module)

                for cycle in cycles:
                    cycle_modules = sorted(cycle)
                    source_file = file_by_module[cycle_modules[0]]
                    cycle_edges = [
                        (module, target, line)
                        for module in cycle
                        for target, line in graph[module]
                        if target in cycle
                    ]
                    line = min((item[2] for item in cycle_edges), default=1)
                    issues.append({
                        "type": "circular", "file": str(source_file), "line": line,
                        "import_name": " -> ".join(cycle_modules),
                        "description": "Local Python modules form a circular import cycle.",
                    })

            unused_count = sum(issue["type"] == "unused" for issue in issues)
            limitations = [
                "External package availability and missing imports were not resolved; no environment imports were attempted."
            ]

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "total_imports": import_count,
                    "circular_imports": len(cycles),
                    "unused_imports": unused_count,
                    "missing_imports": None,
                    "issues": issues,
                    "limitations": limitations,
                },
                output_text=(f"Import analysis: {import_count} statements, "
                             f"{unused_count} unused names, {len(cycles)} local cycles"),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze imports: {str(e)}",
            )


# ===== ANALYZE ARCHITECTURE TOOL =====

class AnalyzeArchitectureInput(BaseModel):
    """Input schema for architectural analysis"""
    path: str = Field(..., description="Project directory path")
    check_layers: bool = Field(default=True, description="Check layered architecture violations")
    check_patterns: bool = Field(default=True, description="Identify design patterns")


class ArchitectureLayer(BaseModel):
    """Architecture layer"""
    name: str
    modules: List[str]
    dependencies: List[str]


class ArchitectureViolation(BaseModel):
    """Architecture violation"""
    type: str
    severity: str
    from_module: str
    to_module: str
    description: str


class AnalyzeArchitectureOutput(BaseModel):
    """Output schema for architectural analysis"""
    path: str
    layers: List[ArchitectureLayer]
    violations: List[ArchitectureViolation]
    patterns_detected: List[str]
    modularity_score: Optional[float] = Field(None, description="Only populated when a documented scoring method is available")
    limitations: List[str] = Field(default_factory=list)


class AnalyzeArchitectureTool(ToolBase):
    """Tool for architectural analysis"""

    @property
    def name(self) -> str:
        return "analyze_architecture"

    @property
    def description(self) -> str:
        return "Analyze project architecture, detect patterns and violations."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeArchitectureInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeArchitectureOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "analysis"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Analyze architecture"""
        path = input_data["path"]
        check_layers = input_data.get("check_layers", True)
        check_patterns = input_data.get("check_patterns", True)

        try:
            logger.info(f"Analyzing architecture: {path}")
            root = Path(path)
            if not root.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            source_root = root if root.is_dir() else root.parent
            files = [root] if root.is_file() else sorted(root.rglob("*.py"))
            files = [candidate for candidate in files if candidate.suffix == ".py"]
            if not files:
                return self.create_result(
                    success=False,
                    error_message="Architecture inventory supports Python source files only; none were found.",
                )

            modules_by_layer: Dict[str, List[str]] = {}
            dependencies_by_layer: Dict[str, set[str]] = {}
            for source_file in files:
                relative = source_file.relative_to(source_root)
                layer = relative.parts[0] if len(relative.parts) > 1 else "_root"
                modules_by_layer.setdefault(layer, []).append(str(relative))
                dependencies_by_layer.setdefault(layer, set())
                tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        dependencies_by_layer[layer].update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        dependencies_by_layer[layer].add(node.module.split(".")[0])
            layers = [
                {"name": layer, "modules": sorted(modules),
                 "dependencies": sorted(dependencies_by_layer[layer])}
                for layer, modules in sorted(modules_by_layer.items())
            ]
            violations = []
            patterns_detected = []
            limitations = [
                "This is a source/module inventory only; no architecture rules were supplied to evaluate violations.",
                "Design-pattern recognition and modularity scoring were not performed.",
            ]
            if not check_layers:
                layers = []
            if not check_patterns:
                patterns_detected = []

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "layers": layers,
                    "violations": violations,
                    "patterns_detected": patterns_detected,
                    "modularity_score": None,
                    "limitations": limitations,
                },
                output_text=(f"Architecture inventory: {len(files)} Python modules in "
                             f"{len(layers)} components; rules and pattern scoring not evaluated."),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze architecture: {str(e)}",
            )


# ===== ANALYZE PERFORMANCE TOOL =====

class AnalyzePerformanceInput(BaseModel):
    """Input schema for performance analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    profile_mode: str = Field(default="static", description="Mode: static (code analysis) or runtime (profiling)")
    find_hotspots: bool = Field(default=True, description="Find performance hotspots")


class PerformanceIssue(BaseModel):
    """Performance issue"""
    severity: str
    category: str = Field(..., description="Category: memory, cpu, io, network")
    file: str
    line: int
    function: str
    description: str
    recommendation: str


class AnalyzePerformanceOutput(BaseModel):
    """Output schema for performance analysis"""
    path: str
    mode: str
    total_issues: int
    issues_by_category: Dict[str, int]
    issues: List[PerformanceIssue]
    hotspots: List[str] = Field(..., description="Performance-critical functions")
    limitations: List[str] = Field(default_factory=list)


class AnalyzePerformanceTool(ToolBase):
    """Tool for performance profiling"""

    @property
    def name(self) -> str:
        return "analyze_performance"

    @property
    def description(self) -> str:
        return "Analyze code for performance issues and bottlenecks."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzePerformanceInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzePerformanceOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "analysis"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Analyze performance"""
        path = input_data["path"]
        profile_mode = input_data.get("profile_mode", "static")
        find_hotspots = input_data.get("find_hotspots", True)

        try:
            logger.info(f"Analyzing performance: {path}, mode={profile_mode}")
            if profile_mode != "static":
                return self.create_result(
                    success=False,
                    error_message="Runtime profiling is not available; use static mode for source heuristics.",
                )
            root = Path(path)
            if not root.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            files = [root] if root.is_file() else sorted(root.rglob("*.py"))
            files = [candidate for candidate in files if candidate.suffix == ".py"]
            if not files:
                return self.create_result(
                    success=False,
                    error_message="Static performance analysis supports Python source only; none were found.",
                )

            class NestedLoopVisitor(ast.NodeVisitor):
                def __init__(self, source_file):
                    self.source_file = str(source_file)
                    self.function = "<module>"
                    self.loop_depth = 0
                    self.issues = []

                def visit_FunctionDef(self, node):
                    previous = self.function
                    self.function = node.name
                    self.generic_visit(node)
                    self.function = previous

                visit_AsyncFunctionDef = visit_FunctionDef

                def _visit_loop(self, node):
                    if self.loop_depth >= 1 and find_hotspots:
                        self.issues.append({
                            "severity": "warning", "category": "cpu",
                            "file": self.source_file, "line": node.lineno,
                            "function": self.function,
                            "description": "Nested loop increases worst-case iteration work.",
                            "recommendation": "Check input bounds and consider indexing, batching, or reducing nested iteration.",
                        })
                    self.loop_depth += 1
                    self.generic_visit(node)
                    self.loop_depth -= 1

                visit_For = _visit_loop
                visit_AsyncFor = _visit_loop
                visit_While = _visit_loop

            issues = []
            for source_file in files:
                tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
                visitor = NestedLoopVisitor(source_file)
                visitor.visit(tree)
                issues.extend(visitor.issues)
            issues_by_category = {"memory": 0, "cpu": len(issues), "io": 0, "network": 0}
            hotspots = [f"{issue['file']}:{issue['line']}:{issue['function']}" for issue in issues]
            limitations = [
                "Static nested-loop heuristics only; no runtime profile, input-size measurement, or memory/network analysis was performed."
            ]

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "mode": profile_mode,
                    "total_issues": len(issues),
                    "issues_by_category": issues_by_category,
                    "issues": issues,
                    "hotspots": hotspots,
                    "limitations": limitations,
                },
                output_text=(f"Static performance scan: {len(issues)} nested-loop hotspots "
                             f"across {len(files)} files; runtime profiling not performed."),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze performance: {str(e)}",
            )
