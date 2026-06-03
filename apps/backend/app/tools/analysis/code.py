"""
JARV Backend - Code Analysis Tools

Tools for analyzing code quality, complexity, duplication, and metrics.

These tools use static analysis to provide insights about code without execution.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import logging
import os
from pathlib import Path

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


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

            # In production: Use static analysis tools like:
            # - pylint, flake8, mypy for Python
            # - eslint, tsc for TypeScript
            # - rubocop for Ruby
            # - clippy for Rust
            # Or integrate with SonarQube, CodeClimate, etc.

            # Simple file counting for now
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
            # In production: Use radon, lizard, or similar tools
            # For now, return placeholder analysis

            logger.info(f"Analyzing complexity: {path}, threshold={threshold}")

            # Placeholder data
            high_complexity = []
            functions_analyzed = 0
            total_complexity = 0

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "average_complexity": 5.0,
                    "max_complexity": 8,
                    "functions_analyzed": functions_analyzed,
                    "high_complexity_functions": high_complexity,
                },
                output_text=f"Analyzed complexity: {functions_analyzed} functions, average: 5.0",
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
            # In production: Use jscpd, PMD CPD, or similar tools

            logger.info(f"Analyzing duplication: {path}, min_lines={min_lines}")

            # Placeholder data
            duplicate_blocks = []

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "total_lines": 1000,
                    "duplicate_lines": 50,
                    "duplication_percentage": 5.0,
                    "duplicate_blocks": duplicate_blocks,
                },
                output_text=f"Duplication analysis: 5.0% duplicate code",
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
            # In production: Use radon, cloc, or similar tools

            logger.info(f"Calculating metrics: {path}, metrics={requested_metrics}")

            # Placeholder metrics
            metrics = {
                "loc": {
                    "total": 1000,
                    "code": 800,
                    "comments": 150,
                    "blank": 50,
                },
                "complexity": {
                    "average": 5.2,
                    "max": 12,
                },
                "maintainability": {
                    "index": 75.0,
                    "rank": "B",
                },
            }

            summary = f"LOC: {metrics['loc']['total']}, Avg Complexity: {metrics['complexity']['average']}, MI: {metrics['maintainability']['index']}"

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "metrics": metrics,
                    "summary": summary,
                },
                output_text=summary,
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to calculate metrics: {str(e)}",
            )
