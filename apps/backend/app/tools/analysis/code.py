"""
JARV Backend - Code Analysis Tools

Tools for analyzing code quality, complexity, duplication, and metrics.

These tools use static analysis to provide insights about code without execution.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import ast
import difflib
import io
import logging
import os
from pathlib import Path
import tokenize

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


def _python_source_files(path: str) -> List[Path]:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    files = [root] if root.is_file() else sorted(root.rglob("*.py"))
    files = [candidate for candidate in files if candidate.suffix == ".py"]
    if not files:
        raise ValueError("No Python source files found; this analyzer supports Python only.")
    return files


def _python_line_metrics(source: str) -> Dict[str, int]:
    lines = source.splitlines()
    comment_lines = set()
    code_lines = set()
    ignored = {
        tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
        tokenize.DEDENT, tokenize.COMMENT, tokenize.ENDMARKER,
    }
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comment_lines.add(token.start[0])
        elif token.type not in ignored:
            code_lines.update(range(token.start[0], token.end[0] + 1))
    blank_lines = {index for index, line in enumerate(lines, start=1) if not line.strip()}
    code_lines -= comment_lines
    code_lines -= blank_lines
    return {
        "total": len(lines),
        "code": len(code_lines),
        "comments": len(comment_lines),
        "blank": len(blank_lines),
    }


# ===== ANALYZE CODE TOOL =====

class AnalyzeCodeInput(BaseModel):
    """Input schema for code analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    language: Optional[str] = Field(None, description="Programming language (auto-detect if None)")
    include_metrics: bool = Field(default=True, description="Include code metrics")
    include_issues: bool = Field(default=True, description="Include code issues")
    max_depth: int = Field(default=3, ge=1, le=10, description="Max directory depth")


class CodeIssue(BaseModel):
    """Code issue information"""
    severity: str = Field(..., description="Severity: error, warning, info")
    category: str = Field(..., description="Category: style, complexity, maintainability, etc.")
    message: str
    file: str
    line: Optional[int] = None
    column: Optional[int] = None


class AnalyzeCodeOutput(BaseModel):
    """Output schema for code analysis"""
    path: str
    language: str
    total_files: int
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    issues: List[CodeIssue]
    quality_score: float = Field(..., description="Overall quality score (0-100)")
    maintainability_index: float = Field(..., description="Maintainability index (0-100)")


class AnalyzeCodeTool(ToolBase):
    """Tool for analyzing code quality and complexity"""

    @property
    def name(self) -> str:
        return "analyze_code"

    @property
    def description(self) -> str:
        return "Analyze code quality, complexity, and identify issues in files or directories."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeCodeInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeCodeOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False  # Analysis is read-only

    @property
    def category(self) -> str:
        return "analysis"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Analyze code quality"""
        path = input_data["path"]
        language = input_data.get("language")
        include_metrics = input_data.get("include_metrics", True)
        include_issues = input_data.get("include_issues", True)
        max_depth = input_data.get("max_depth", 3)

        try:
            # Validate path exists
            if not os.path.exists(path):
                return self.create_result(
                    success=False,
                    error_message=f"Path not found: {path}",
                )

            # Count lines and analyze
            total_files = 0
            total_lines = 0
            code_lines = 0
            comment_lines = 0
            blank_lines = 0
            issues = []

            # Line metrics: files, total, code, comment and blank lines. Linting and type checks are
            # the quality tools (analyze_style, analyze_types) and the agents' run_command.
            path_obj = Path(path)
            if path_obj.is_file():
                total_files = 1
                # Count lines in file
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        total_lines += 1
                        stripped = line.strip()
                        if not stripped:
                            blank_lines += 1
                        elif stripped.startswith('#') or stripped.startswith('//'):
                            comment_lines += 1
                        else:
                            code_lines += 1
            else:
                # Directory analysis
                for file_path in path_obj.rglob('*'):
                    if file_path.is_file() and file_path.suffix in ['.py', '.js', '.ts', '.java', '.go', '.rs']:
                        total_files += 1
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                for line in f:
                                    total_lines += 1
                                    stripped = line.strip()
                                    if not stripped:
                                        blank_lines += 1
                                    elif stripped.startswith('#') or stripped.startswith('//'):
                                        comment_lines += 1
                                    else:
                                        code_lines += 1
                        except Exception:
                            pass

            # Calculate quality score (simplified)
            comment_ratio = comment_lines / max(code_lines, 1)
            quality_score = min(100, 50 + (comment_ratio * 50))
            maintainability_index = quality_score  # Simplified

            # Auto-detect language
            if not language:
                if path.endswith('.py'):
                    language = 'python'
                elif path.endswith('.js'):
                    language = 'javascript'
                elif path.endswith('.ts'):
                    language = 'typescript'
                elif path.endswith('.java'):
                    language = 'java'
                elif path.endswith('.go'):
                    language = 'go'
                else:
                    language = 'unknown'

            logger.info(f"Analyzed code: {path}, {total_files} files, {total_lines} lines")

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "language": language,
                    "total_files": total_files,
                    "total_lines": total_lines,
                    "code_lines": code_lines,
                    "comment_lines": comment_lines,
                    "blank_lines": blank_lines,
                    "issues": issues,
                    "quality_score": quality_score,
                    "maintainability_index": maintainability_index,
                },
                output_text=f"Analyzed {total_files} files: {code_lines} code lines, quality score: {quality_score:.1f}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze code: {str(e)}",
            )


# ===== ANALYZE COMPLEXITY TOOL =====

class AnalyzeComplexityInput(BaseModel):
    """Input schema for complexity analysis"""
    path: str = Field(..., description="File or directory path to analyze")
    threshold: int = Field(default=10, ge=1, le=50, description="Complexity threshold for warnings")


class ComplexityResult(BaseModel):
    """Complexity analysis result"""
    file: str
    function: str
    complexity: int
    line: int


class AnalyzeComplexityOutput(BaseModel):
    """Output schema for complexity analysis"""
    path: str
    average_complexity: float
    max_complexity: int
    functions_analyzed: int
    high_complexity_functions: List[ComplexityResult] = Field(..., description="Functions exceeding threshold")


class AnalyzeComplexityTool(ToolBase):
    """Tool for calculating cyclomatic complexity"""

    @property
    def name(self) -> str:
        return "analyze_complexity"

    @property
    def description(self) -> str:
        return "Calculate cyclomatic complexity of functions/methods in code."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeComplexityInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeComplexityOutput

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
        """Calculate cyclomatic complexity"""
        path = input_data["path"]
        threshold = input_data.get("threshold", 10)

        try:
            logger.info(f"Analyzing complexity: {path}, threshold={threshold}")
            path_obj = Path(path)
            if not path_obj.exists():
                return self.create_result(success=False, error_message=f"Path not found: {path}")
            files = [path_obj] if path_obj.is_file() else sorted(path_obj.rglob("*.py"))
            files = [candidate for candidate in files if candidate.suffix == ".py"]
            if not files:
                return self.create_result(
                    success=False,
                    error_message="Complexity analysis supports Python source files only; none were found.",
                )

            class FunctionComplexityVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.functions = []
                    self._current_name = None
                    self._current_line = None
                    self._complexity = 0

                def visit_FunctionDef(self, node):
                    self._visit_function(node)

                def visit_AsyncFunctionDef(self, node):
                    self._visit_function(node)

                def _visit_function(self, node):
                    previous = (self._current_name, self._current_line, self._complexity)
                    self._current_name = node.name
                    self._current_line = node.lineno
                    self._complexity = 1
                    for child in node.body:
                        self.visit(child)
                    self.functions.append((self._current_name, self._current_line, self._complexity))
                    self._current_name, self._current_line, self._complexity = previous

                def visit_If(self, node):
                    self._complexity += 1
                    self.generic_visit(node)

                def visit_For(self, node):
                    self._complexity += 1
                    self.generic_visit(node)

                visit_AsyncFor = visit_For

                def visit_While(self, node):
                    self._complexity += 1
                    self.generic_visit(node)

                def visit_IfExp(self, node):
                    self._complexity += 1
                    self.generic_visit(node)

                def visit_BoolOp(self, node):
                    self._complexity += max(0, len(node.values) - 1)
                    self.generic_visit(node)

                def visit_ExceptHandler(self, node):
                    self._complexity += 1
                    self.generic_visit(node)

                def visit_Match(self, node):
                    self._complexity += sum(
                        not (isinstance(case.pattern, ast.MatchAs) and case.pattern.name is None)
                        for case in node.cases
                    )
                    self.generic_visit(node)

                def visit_Lambda(self, node):
                    return

            measured = []
            for source_file in files:
                try:
                    source = source_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(source_file))
                except (OSError, UnicodeError, SyntaxError) as exc:
                    return self.create_result(
                        success=False,
                        error_message=f"Unable to parse {source_file}: {exc}",
                    )
                visitor = FunctionComplexityVisitor()
                visitor.visit(tree)
                measured.extend((str(source_file), name, complexity, line)
                                for name, line, complexity in visitor.functions)

            if not measured:
                return self.create_result(
                    success=False,
                    error_message="No Python functions were found to analyze.",
                )

            total_complexity = sum(item[2] for item in measured)
            functions_analyzed = len(measured)
            high_complexity = [
                {"file": file_name, "function": function_name,
                 "complexity": complexity, "line": line}
                for file_name, function_name, complexity, line in measured
                if complexity > threshold
            ]
            average_complexity = total_complexity / functions_analyzed
            max_complexity = max(item[2] for item in measured)

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "average_complexity": average_complexity,
                    "max_complexity": max_complexity,
                    "functions_analyzed": functions_analyzed,
                    "high_complexity_functions": high_complexity,
                },
                output_text=(f"Analyzed complexity: {functions_analyzed} functions, "
                             f"average: {average_complexity:.2f}, max: {max_complexity}"),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze complexity: {str(e)}",
            )


# ===== ANALYZE DUPLICATION TOOL =====

class AnalyzeDuplicationInput(BaseModel):
    """Input schema for duplication detection"""
    path: str = Field(..., description="File or directory path to analyze")
    min_lines: int = Field(default=6, ge=3, le=50, description="Minimum lines for duplicate detection")
    ignore_whitespace: bool = Field(default=True, description="Ignore whitespace differences")


class DuplicateBlock(BaseModel):
    """Duplicate code block"""
    file1: str
    line1: int
    file2: str
    line2: int
    lines: int
    tokens: int


class AnalyzeDuplicationOutput(BaseModel):
    """Output schema for duplication detection"""
    path: str
    total_lines: int
    duplicate_lines: int
    duplication_percentage: float
    duplicate_blocks: List[DuplicateBlock]


class AnalyzeDuplicationTool(ToolBase):
    """Tool for detecting code duplication"""

    @property
    def name(self) -> str:
        return "analyze_duplication"

    @property
    def description(self) -> str:
        return "Detect duplicate code blocks across files."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeDuplicationInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeDuplicationOutput

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
        """Detect code duplication"""
        path = input_data["path"]
        min_lines = input_data.get("min_lines", 6)
        ignore_whitespace = input_data.get("ignore_whitespace", True)

        try:
            logger.info(f"Analyzing duplication: {path}, min_lines={min_lines}")
            files = _python_source_files(path)
            file_lines = {}
            total_lines = 0
            for source_file in files:
                lines = source_file.read_text(encoding="utf-8").splitlines()
                if ignore_whitespace:
                    lines = [line.strip() for line in lines]
                file_lines[source_file] = lines
                total_lines += len(lines)

            duplicate_blocks = []
            duplicate_lines = 0
            for file_index, file1 in enumerate(files):
                for file2 in files[file_index + 1:]:
                    matcher = difflib.SequenceMatcher(
                        None, file_lines[file1], file_lines[file2], autojunk=False)
                    for block in matcher.get_matching_blocks():
                        if block.size < min_lines:
                            continue
                        duplicate_lines += block.size
                        duplicate_blocks.append({
                            "file1": str(file1),
                            "line1": block.a + 1,
                            "file2": str(file2),
                            "line2": block.b + 1,
                            "lines": block.size,
                            "tokens": sum(len(line.split()) for line in file_lines[file1][block.a:block.a + block.size]),
                        })

            duplication_percentage = (
                duplicate_lines * 100.0 / total_lines if total_lines else 0.0
            )

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "total_lines": total_lines,
                    "duplicate_lines": duplicate_lines,
                    "duplication_percentage": duplication_percentage,
                    "duplicate_blocks": duplicate_blocks,
                },
                output_text=(f"Duplication analysis: {duplicate_lines} duplicate lines "
                             f"({duplication_percentage:.2f}%) across {len(files)} files"),
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze duplication: {str(e)}",
            )


# ===== ANALYZE METRICS TOOL =====

class AnalyzeMetricsInput(BaseModel):
    """Input schema for metrics calculation"""
    path: str = Field(..., description="File or directory path to analyze")
    metrics: List[str] = Field(
        default=["loc", "complexity", "maintainability"],
        description="Metrics to calculate: loc, complexity, maintainability, halstead"
    )


class AnalyzeMetricsOutput(BaseModel):
    """Output schema for metrics calculation"""
    path: str
    metrics: Dict[str, Any] = Field(..., description="Calculated metrics")
    summary: str


class AnalyzeMetricsTool(ToolBase):
    """Tool for calculating code metrics"""

    @property
    def name(self) -> str:
        return "analyze_metrics"

    @property
    def description(self) -> str:
        return "Calculate comprehensive code metrics (LOC, complexity, maintainability, etc.)."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyzeMetricsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyzeMetricsOutput

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
        """Calculate code metrics"""
        path = input_data["path"]
        requested_metrics = input_data.get("metrics", ["loc", "complexity", "maintainability"])

        try:
            logger.info(f"Calculating metrics: {path}, metrics={requested_metrics}")
            files = _python_source_files(path)
            totals = {"total": 0, "code": 0, "comments": 0, "blank": 0}
            for source_file in files:
                line_counts = _python_line_metrics(source_file.read_text(encoding="utf-8"))
                for key in totals:
                    totals[key] += line_counts[key]

            metrics = {}
            limitations = []
            if "loc" in requested_metrics:
                metrics["loc"] = totals
            unsupported = set(requested_metrics) - {"loc", "complexity", "maintainability"}
            if unsupported:
                limitations.append(f"Unsupported metrics: {', '.join(sorted(unsupported))}")
            if "complexity" in requested_metrics or "maintainability" in requested_metrics:
                complexity_result = await AnalyzeComplexityTool(self.config).run(
                    {"path": path}, context)
                if not complexity_result.success:
                    return complexity_result
                complexity = complexity_result.result_data
                if "complexity" in requested_metrics:
                    metrics["complexity"] = {
                        "average": complexity["average_complexity"],
                        "max": complexity["max_complexity"],
                        "functions_analyzed": complexity["functions_analyzed"],
                    }
                if "maintainability" in requested_metrics:
                    metrics["maintainability"] = {
                        "supported": False,
                        "reason": "A validated Halstead volume analyzer is not available; no maintainability index is fabricated.",
                    }
                    limitations.append("Maintainability index was not calculated.")

            summary_parts = []
            if "loc" in metrics:
                summary_parts.append(f"LOC: {totals['total']} total, {totals['code']} code")
            if "complexity" in metrics:
                summary_parts.append(
                    f"average complexity: {metrics['complexity']['average']:.2f}")
            if limitations:
                summary_parts.append("Limitations: " + " ".join(limitations))
            summary = "; ".join(summary_parts) or "No supported metrics were requested."

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "metrics": metrics,
                    "summary": summary,
                    "limitations": limitations,
                },
                output_text=summary,
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to calculate metrics: {str(e)}",
            )
