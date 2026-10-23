"""Behavioral tests for local source-analysis tools."""
import asyncio

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.tools.analysis.code import (
    AnalyzeComplexityTool,
    AnalyzeDuplicationTool,
    AnalyzeMetricsTool,
)
from app.tools.analysis.quality import (
    AnalyzeCoverageTool,
    AnalyzeSecurityTool,
    AnalyzeStyleTool,
    AnalyzeTypesTool,
)
from app.tools.analysis.structure import (
    AnalyzeArchitectureTool,
    AnalyzeDependenciesTool,
    AnalyzeImportsTool,
    AnalyzePerformanceTool,
)


def test_complexity_tool_reports_real_python_function_branches(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "def simple(value):\n"
        "    return value\n\n"
        "def branched(items):\n"
        "    for item in items:\n"
        "        if item:\n"
        "            continue\n"
        "    return None\n",
        encoding="utf-8",
    )
    tool = AnalyzeComplexityTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run(
        {"path": str(source), "threshold": 2}, ToolContext()))

    assert result.success is True
    assert result.result_data["functions_analyzed"] == 2
    assert result.result_data["average_complexity"] == 2.0
    assert result.result_data["max_complexity"] == 3
    assert result.result_data["high_complexity_functions"] == [{
        "file": str(source),
        "function": "branched",
        "complexity": 3,
        "line": 4,
    }]


def test_duplication_tool_reports_real_matching_blocks(tmp_path):
    (tmp_path / "first.py").write_text(
        "first = 1\nshared_one()\nshared_two()\nshared_three()\nlast = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "second.py").write_text(
        "second = 2\nshared_one()\nshared_two()\nshared_three()\nlast = 2\n",
        encoding="utf-8",
    )
    tool = AnalyzeDuplicationTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run(
        {"path": str(tmp_path), "min_lines": 3}, ToolContext()))

    assert result.success is True
    assert result.result_data["total_lines"] == 10
    assert result.result_data["duplicate_lines"] == 3
    assert result.result_data["duplication_percentage"] == 30.0
    assert result.result_data["duplicate_blocks"][0]["line1"] == 2
    assert result.result_data["duplicate_blocks"][0]["line2"] == 2


def test_metrics_tool_computes_loc_and_discloses_unsupported_index(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "def sample(value):\n    # actual comment\n    if value:\n        return value\n    return 0\n",
        encoding="utf-8",
    )
    tool = AnalyzeMetricsTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(source)}, ToolContext()))

    assert result.success is True
    assert result.result_data["metrics"]["loc"] == {
        "total": 5, "code": 4, "comments": 1, "blank": 0,
    }
    assert result.result_data["metrics"]["complexity"]["average"] == 2.0
    assert result.result_data["metrics"]["maintainability"]["supported"] is False
    assert any("not calculated" in limitation
               for limitation in result.result_data["limitations"])


def test_style_tool_reports_real_whitespace_and_line_length_issues(tmp_path):
    source = tmp_path / "style.py"
    source.write_text("value = 1  \n" + "# " + ("x" * 80) + "\n", encoding="utf-8")
    tool = AnalyzeStyleTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run(
        {"path": str(source), "style_guide": "pep8"}, ToolContext()))

    assert result.success is True
    assert result.result_data["total_violations"] == 2
    assert {issue["code"] for issue in result.result_data["violations"]} == {"W291", "E501"}
    assert result.result_data["fixed_count"] == 0


def test_types_tool_reports_annotation_presence_not_fabricated_checker_results(tmp_path):
    source = tmp_path / "types.py"
    source.write_text(
        "def typed(value: int) -> int:\n    return value\n\n"
        "def untyped(value):\n    return value\n",
        encoding="utf-8",
    )
    tool = AnalyzeTypesTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(source)}, ToolContext()))

    assert result.success is True
    assert result.result_data["type_coverage"] == 50.0
    assert result.result_data["errors"] == 0
    assert result.result_data["analysis_mode"] == "annotation_presence_only"
    assert any(issue["file"] == str(source) for issue in result.result_data["issues"])


def test_coverage_tool_parses_real_lcov_counts(tmp_path):
    report = tmp_path / "lcov.info"
    report.write_text(
        "TN:\nSF:sample.py\nDA:1,1\nDA:2,0\nLF:2\nLH:1\nend_of_record\n",
        encoding="utf-8",
    )
    tool = AnalyzeCoverageTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(report), "threshold": 80}, ToolContext()))

    assert result.success is True
    assert result.result_data["overall_coverage"] == 50.0
    assert result.result_data["lines_total"] == 2
    assert result.result_data["lines_covered"] == 1
    assert result.result_data["files_analyzed"] == 1
    assert result.result_data["below_threshold"] == ["sample.py"]


def test_security_tool_reports_real_findings_without_copying_secret(tmp_path):
    secret = "AKIAIOSFODNN7EXAMPLE"
    source = tmp_path / "unsafe.py"
    source.write_text(f'key = "{secret}"\nvalue = eval("1 + 1")\n', encoding="utf-8")
    tool = AnalyzeSecurityTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run(
        {"path": str(source), "include_dependencies": True}, ToolContext()))

    assert result.success is True
    assert result.result_data["total_issues"] == 2
    assert result.result_data["dependency_vulnerabilities"] == 0
    assert result.result_data["dependency_scan_performed"] is False
    assert secret not in str(result.result_data)
    assert {issue["category"] for issue in result.result_data["issues"]} == {
        "aws_access_key", "eval",
    }


def test_dependency_tool_reads_real_pyproject_requirements(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text(
        "[project]\nname = 'sample'\ndependencies = ['fastapi>=0.110', 'httpx==0.27.0']\n"
        "[project.optional-dependencies]\ndev = ['pytest>=8']\n",
        encoding="utf-8",
    )
    tool = AnalyzeDependenciesTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(project)}, ToolContext()))

    assert result.success is True
    assert result.result_data["total_dependencies"] == 2
    assert {dep["name"] for dep in result.result_data["dependencies"]} == {"fastapi", "httpx"}
    assert result.result_data["dependencies"][0]["current_version"]
    assert result.result_data["outdated_count"] is None
    assert result.result_data["vulnerable_count"] is None
    assert any("registry" in item.lower() for item in result.result_data["limitations"])


def test_import_tool_finds_real_unused_and_circular_local_imports(tmp_path):
    (tmp_path / "first.py").write_text(
        "import os\nfrom second import second_value\n\n"
        "def first_value():\n    return second_value()\n",
        encoding="utf-8",
    )
    (tmp_path / "second.py").write_text(
        "from first import first_value\n\n"
        "def second_value():\n    return first_value()\n",
        encoding="utf-8",
    )
    tool = AnalyzeImportsTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(tmp_path)}, ToolContext()))

    assert result.success is True, result.error_message
    assert result.result_data["total_imports"] == 3
    assert result.result_data["unused_imports"] == 1
    assert result.result_data["circular_imports"] == 1
    assert result.result_data["missing_imports"] is None
    assert any(issue["type"] == "unused" and issue["import_name"] == "os"
               for issue in result.result_data["issues"])
    assert any(issue["type"] == "circular" for issue in result.result_data["issues"])


def test_architecture_tool_reports_real_module_inventory(tmp_path):
    package = tmp_path / "service"
    package.mkdir()
    (package / "api.py").write_text("from service import core\n", encoding="utf-8")
    (package / "core.py").write_text("def run():\n    return True\n", encoding="utf-8")
    tool = AnalyzeArchitectureTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(tmp_path)}, ToolContext()))

    assert result.success is True
    assert result.result_data["layers"]
    assert result.result_data["layers"][0]["name"] == "service"
    assert len(result.result_data["layers"][0]["modules"]) == 2
    assert result.result_data["modularity_score"] is None
    assert any("rules" in limit.lower() for limit in result.result_data["limitations"])


def test_performance_tool_finds_real_nested_python_loops(tmp_path):
    source = tmp_path / "slow.py"
    source.write_text(
        "def work(items):\n"
        "    for left in items:\n"
        "        for right in items:\n"
        "            print(left, right)\n",
        encoding="utf-8",
    )
    tool = AnalyzePerformanceTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))

    result = asyncio.run(tool.run({"path": str(source)}, ToolContext()))

    assert result.success is True
    assert result.result_data["total_issues"] == 1
    assert result.result_data["issues"][0]["function"] == "work"
    assert result.result_data["issues"][0]["line"] == 3
    assert result.result_data["mode"] == "static"
    assert any("runtime" in limit.lower() for limit in result.result_data["limitations"])