"""
JARV Backend - Quality Analysis Tools

Tools for code style, type checking, coverage, and security analysis.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import ast
import json
import logging
from pathlib import Path
import xml.etree.ElementTree as ET

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.agents.specialists._helpers import scan_dangerous, scan_secrets

logger = logging.getLogger(__name__)


# ===== ANALYZE STYLE TOOL =====

class AnalyzeStyleInput(BaseModel):
    """Input schema for style analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    style_guide: str = Field(default="pep8", description="Style guide: pep8, google, airbnb, standard")
    fix: bool = Field(default=False, description="Auto-fix issues if possible")


class StyleViolation(BaseModel):
    """Style violation"""
    file: str
    line: int
    column: int
    code: str = Field(..., description="Violation code (e.g., E501)")
    message: str
    severity: str


class AnalyzeStyleOutput(BaseModel):
    """Output schema for style analysis"""
    path: str
    style_guide: str
    total_violations: int
    violations_by_severity: Dict[str, int]
    violations: List[StyleViolation]
    fixed_count: int = Field(..., description="Number of auto-fixed issues")


class AnalyzeStyleTool(ToolBase):
    """Tool for checking code style compliance"""

    @property
    def name(self) -> str:
        return "analyze_style"

    @property
    def description(self) -> str:
        return "Check code style compliance against style guides (PEP8, Google, Airbnb, etc.)."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeStyleInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeStyleOutput

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
        """Check code style"""
        path = input_data["path"]
        style_guide = input_data.get("style_guide", "pep8")
        fix = input_data.get("fix", False)

        try:
            logger.info(f"Analyzing style: {path}, guide={style_guide}, fix={fix}")
            if style_guide.lower() != "pep8":
                return self.create_result(
                    success=False,
                    error_message=f"Style guide '{style_guide}' is not supported; only pep8 is implemented.",
                )
            if fix and int(self.config.authority_level) < int(AuthorityLevel.LEVEL_2_FILE_OPERATIONS):
                return self.create_result(
                    success=False,
                    error_message="Fixing style edits files, which needs file authority (level 2); nothing was changed.",
                )
            root = Path(path)
            if not root.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            files = [root] if root.is_file() else sorted(root.rglob("*.py"))
            files = [candidate for candidate in files if candidate.suffix == ".py"]
            if not files:
                return self.create_result(
                    success=False,
                    error_message="PEP 8 analysis supports Python source files only; none were found.",
                )

            violations = []
            for source_file in files:
                for line_number, line in enumerate(
                    source_file.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if line.rstrip(" \t") != line:
                        code = "W291" if line.strip() else "W293"
                        violations.append({
                            "file": str(source_file), "line": line_number,
                            "column": len(line.rstrip(" \t")) + 1, "code": code,
                            "message": "Trailing whitespace.", "severity": "warning",
                        })
                    if len(line) > 79:
                        violations.append({
                            "file": str(source_file), "line": line_number,
                            "column": 80, "code": "E501",
                            "message": f"Line too long ({len(line)} > 79 characters).",
                            "severity": "warning",
                        })
            fixed_count = 0
            if fix:
                # Trailing whitespace (W291/W293) is removed; long lines (E501) need a person or a
                # formatter, so they stay reported.
                fixable = {issue["file"] for issue in violations if issue["code"] in ("W291", "W293")}
                for name in fixable:
                    source = Path(name)
                    text = source.read_text(encoding="utf-8")
                    cleaned = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
                    if cleaned != text:
                        source.write_text(cleaned, encoding="utf-8")
                fixed_count = sum(1 for issue in violations if issue["code"] in ("W291", "W293"))
                violations = [issue for issue in violations if issue["code"] not in ("W291", "W293")]
            by_severity = {"error": 0, "warning": 0, "info": 0}
            for issue in violations:
                by_severity[issue["severity"]] += 1

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "style_guide": style_guide,
                    "total_violations": len(violations),
                    "violations_by_severity": by_severity,
                    "violations": violations,
                    "fixed_count": fixed_count,
                },
                output_text=(f"PEP 8 subset check complete: {len(violations)} violations across {len(files)} files"
                             + (f"; removed trailing whitespace on {fixed_count} line(s)" if fixed_count else "")),
                files_affected=sorted({str(f) for f in files}) if fixed_count else [],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze style: {str(e)}",
            )


# ===== ANALYZE TYPES TOOL =====

class AnalyzeTypesInput(BaseModel):
    """Input schema for type analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    strict: bool = Field(default=False, description="Strict type checking mode")


class TypeIssue(BaseModel):
    """Type checking issue"""
    file: str
    line: int
    column: int
    severity: str
    message: str
    code: Optional[str] = None


class AnalyzeTypesOutput(BaseModel):
    """Output schema for type analysis"""
    path: str
    total_issues: int
    errors: int
    warnings: int
    type_coverage: float = Field(..., description="Percentage of typed code")
    issues: List[TypeIssue]


class AnalyzeTypesTool(ToolBase):
    """Tool for type checking and inference"""

    @property
    def name(self) -> str:
        return "analyze_types"

    @property
    def description(self) -> str:
        return "Perform type checking and calculate type coverage."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeTypesInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeTypesOutput

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
        """Check types"""
        path = input_data["path"]
        strict = input_data.get("strict", False)

        try:
            logger.info(f"Analyzing types: {path}, strict={strict}")
            root = Path(path)
            if not root.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            files = [root] if root.is_file() else sorted(root.rglob("*.py"))
            files = [candidate for candidate in files if candidate.suffix == ".py"]
            if not files:
                return self.create_result(
                    success=False,
                    error_message="Annotation analysis supports Python source files only; none were found.",
                )

            issues = []
            annotated = 0
            slots = 0
            for source_file in files:
                try:
                    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
                except (OSError, UnicodeError, SyntaxError) as exc:
                    return self.create_result(
                        success=False, error_message=f"Unable to parse {source_file}: {exc}")
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    arguments = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
                    if node.args.vararg:
                        arguments.append(node.args.vararg)
                    if node.args.kwarg:
                        arguments.append(node.args.kwarg)
                    for argument in arguments:
                        slots += 1
                        if argument.annotation is not None:
                            annotated += 1
                        else:
                            issues.append({
                                "file": str(source_file), "line": argument.lineno,
                                "column": argument.col_offset, "severity": "warning",
                                "message": f"Parameter '{argument.arg}' has no annotation.",
                                "code": "missing-parameter-annotation",
                            })
                    slots += 1
                    if node.returns is not None:
                        annotated += 1
                    else:
                        issues.append({
                            "file": str(source_file), "line": node.lineno,
                            "column": node.col_offset, "severity": "warning",
                            "message": f"Function '{node.name}' has no return annotation.",
                            "code": "missing-return-annotation",
                        })
            errors = sum(issue["severity"] == "error" for issue in issues)
            warnings = len(issues) - errors
            coverage = annotated * 100.0 / slots if slots else 0.0

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "total_issues": len(issues),
                    "errors": errors,
                    "warnings": warnings,
                    "type_coverage": coverage,
                    "issues": issues,
                    "analysis_mode": "annotation_presence_only",
                    "limitations": [
                        "This measures annotation presence; it does not perform semantic type checking.",
                        "Strict mode is informational until a configured Python type checker is available." if strict else "",
                    ],
                },
                output_text=(f"Annotation presence: {coverage:.1f}% across {slots} parameter/return slots; "
                             f"{len(issues)} missing annotations. No semantic type checker was run."),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze types: {str(e)}",
            )


# ===== ANALYZE COVERAGE TOOL =====

class AnalyzeCoverageInput(BaseModel):
    """Input schema for coverage analysis"""
    path: str = Field(..., description="Path to coverage report or project")
    report_format: str = Field(default="lcov", description="Report format: lcov, cobertura, json")
    threshold: float = Field(default=80.0, ge=0.0, le=100.0, description="Minimum coverage threshold")


class CoverageResult(BaseModel):
    """Coverage analysis result"""
    file: str
    lines_total: int
    lines_covered: int
    coverage_percentage: float
    uncovered_lines: List[int]


class AnalyzeCoverageOutput(BaseModel):
    """Output schema for coverage analysis"""
    path: str
    overall_coverage: float
    lines_total: int
    lines_covered: int
    files_analyzed: int
    below_threshold: List[str] = Field(..., description="Files below coverage threshold")
    file_coverage: List[CoverageResult]


class AnalyzeCoverageTool(ToolBase):
    """Tool for code coverage analysis"""

    @property
    def name(self) -> str:
        return "analyze_coverage"

    @property
    def description(self) -> str:
        return "Analyze code coverage from test runs."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeCoverageInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeCoverageOutput

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
        """Analyze coverage"""
        path = input_data["path"]
        report_format = input_data.get("report_format", "lcov")
        threshold = input_data.get("threshold", 80.0)

        try:
            logger.info(f"Analyzing coverage: {path}, format={report_format}, threshold={threshold}")
            file_coverage = []
            report = Path(path)
            if not report.is_file():
                return self.create_result(
                    success=False,
                    error_message="A coverage report file is required; project source alone is not coverage evidence.",
                )

            if report_format == "lcov":
                records = []
                current = None
                for line in report.read_text(encoding="utf-8").splitlines():
                    if line.startswith("SF:"):
                        current = {"file": line[3:], "lines": {}}
                    elif current is not None and line.startswith("DA:"):
                        line_no, hits, *_ = line[3:].split(",")
                        current["lines"][int(line_no)] = int(hits)
                    elif current is not None and line == "end_of_record":
                        records.append(current)
                        current = None
                if current is not None:
                    records.append(current)
                for record in records:
                    hits = record["lines"]
                    total = len(hits)
                    covered = sum(count > 0 for count in hits.values())
                    file_coverage.append({
                        "file": record["file"], "lines_total": total,
                        "lines_covered": covered,
                        "coverage_percentage": covered * 100.0 / total if total else 0.0,
                        "uncovered_lines": sorted(line_no for line_no, count in hits.items() if count == 0),
                    })
            elif report_format == "json":
                payload = json.loads(report.read_text(encoding="utf-8"))
                for file_name, data in payload.get("files", {}).items():
                    summary = data.get("summary", {})
                    total = int(summary.get("num_statements", 0))
                    covered = int(summary.get("covered_lines", 0))
                    missing = data.get("missing_lines", [])
                    file_coverage.append({
                        "file": file_name, "lines_total": total,
                        "lines_covered": covered,
                        "coverage_percentage": covered * 100.0 / total if total else 0.0,
                        "uncovered_lines": sorted(int(line) for line in missing),
                    })
            elif report_format == "cobertura":
                root = ET.parse(report).getroot()
                for class_node in root.findall(".//class"):
                    lines = class_node.findall("./lines/line")
                    total = len(lines)
                    covered = sum(int(line.attrib.get("hits", "0")) > 0 for line in lines)
                    file_coverage.append({
                        "file": class_node.attrib.get("filename", ""),
                        "lines_total": total,
                        "lines_covered": covered,
                        "coverage_percentage": covered * 100.0 / total if total else 0.0,
                        "uncovered_lines": sorted(
                            int(line.attrib["number"]) for line in lines
                            if int(line.attrib.get("hits", "0")) == 0
                        ),
                    })
            else:
                return self.create_result(
                    success=False,
                    error_message=f"Unsupported coverage format: {report_format}",
                )

            if not file_coverage:
                return self.create_result(
                    success=False, error_message="The report contained no measurable line coverage.")
            lines_total = sum(item["lines_total"] for item in file_coverage)
            lines_covered = sum(item["lines_covered"] for item in file_coverage)
            overall = lines_covered * 100.0 / lines_total if lines_total else 0.0
            below_threshold = [
                item["file"] for item in file_coverage
                if item["coverage_percentage"] < threshold
            ]

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "overall_coverage": overall,
                    "lines_total": lines_total,
                    "lines_covered": lines_covered,
                    "files_analyzed": len(file_coverage),
                    "below_threshold": below_threshold,
                    "file_coverage": file_coverage,
                },
                output_text=f"Coverage: {overall:.1f}% ({lines_covered}/{lines_total} lines)",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze coverage: {str(e)}",
            )


# ===== ANALYZE SECURITY TOOL =====

class AnalyzeSecurityInput(BaseModel):
    """Input schema for security analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    severity_threshold: str = Field(default="medium", description="Minimum severity: low, medium, high, critical")
    include_dependencies: bool = Field(default=True, description="Check dependencies for vulnerabilities")


class SecurityIssue(BaseModel):
    """Security vulnerability"""
    severity: str
    category: str = Field(..., description="Category: injection, xss, hardcoded_secret, etc.")
    title: str
    description: str
    file: str
    line: Optional[int] = None
    cwe: Optional[str] = Field(None, description="CWE identifier")
    recommendation: str


class AnalyzeSecurityOutput(BaseModel):
    """Output schema for security analysis"""
    path: str
    total_issues: int
    critical: int
    high: int
    medium: int
    low: int
    issues: List[SecurityIssue]
    dependency_vulnerabilities: int


class AnalyzeSecurityTool(ToolBase):
    """Tool for security vulnerability scanning"""

    @property
    def name(self) -> str:
        return "analyze_security"

    @property
    def description(self) -> str:
        return "Scan code for security vulnerabilities and unsafe patterns."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeSecurityInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeSecurityOutput

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
        """Scan for security issues"""
        path = input_data["path"]
        severity_threshold = input_data.get("severity_threshold", "medium")
        include_dependencies = input_data.get("include_dependencies", True)

        try:
            logger.info(f"Scanning security: {path}, threshold={severity_threshold}")
            threshold_levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            if severity_threshold not in threshold_levels:
                return self.create_result(
                    success=False,
                    error_message="severity_threshold must be low, medium, high, or critical.",
                )

            root = Path(path)
            if not root.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            supported = {
                ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
                ".rb", ".php", ".yaml", ".yml", ".json", ".toml", ".ini", ".env", ".sh",
            }
            files = [root] if root.is_file() else sorted(root.rglob("*"))
            files = [file for file in files if file.is_file() and file.suffix.lower() in supported
                     and not any(part in {".git", "node_modules", ".venv", "venv"}
                                 for part in file.parts)]
            if not files:
                return self.create_result(
                    success=False, error_message="No supported source or configuration files were found.")

            severity_floor = threshold_levels[severity_threshold]
            issues = []
            scan_errors = []
            for source_file in files:
                try:
                    lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError as exc:
                    scan_errors.append(f"Unreadable file skipped: {source_file} ({exc})")
                    continue
                for line_number, line in enumerate(lines, start=1):
                    for finding in scan_secrets(line) + scan_dangerous(line):
                        is_secret = finding["type"] == "secret"
                        severity = "critical" if is_secret else "high"
                        if threshold_levels[severity] < severity_floor:
                            continue
                        pattern = finding["pattern"]
                        issues.append({
                            "severity": severity,
                            "category": pattern,
                            "title": "Secret-like value detected" if is_secret else "Potentially dangerous call detected",
                            "description": (
                                f"A line matches the {pattern} static pattern. "
                                "Matched source text is intentionally not copied into the result."
                            ),
                            "file": str(source_file),
                            "line": line_number,
                            "cwe": None,
                            "recommendation": (
                                "Remove and rotate exposed credentials." if is_secret
                                else "Review the call and use a safer alternative where possible."
                            ),
                        })

            if not files or len(scan_errors) == len(files):
                return self.create_result(
                    success=False,
                    error_message="No files could be scanned.",
                    result_data={"limitations": scan_errors},
                )
            counts = {level: sum(issue["severity"] == level for issue in issues)
                      for level in ("critical", "high", "medium", "low")}
            limitations = [
                "This is a lightweight static regex scan, not full SAST; no findings do not prove security.",
            ]
            if include_dependencies:
                limitations.append("Dependency CVE scanning is unavailable; no package registry or advisory database was queried.")
            limitations.extend(scan_errors)

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "total_issues": len(issues),
                    **counts,
                    "issues": issues,
                    "dependency_vulnerabilities": 0,
                    "dependency_scan_performed": False,
                    "files_scanned": len(files) - len(scan_errors),
                    "limitations": limitations,
                },
                output_text=(f"Static security scan: {len(issues)} findings across "
                             f"{len(files) - len(scan_errors)} files; dependency scanning unavailable."),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze security: {str(e)}",
            )
