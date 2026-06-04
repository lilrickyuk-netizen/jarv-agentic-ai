"""
JARV Backend - Tools API

REST API endpoints for tool management and discovery.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.core.tools import get_registry, ToolMetadata
from app.core.agents.base import AuthorityLevel

router = APIRouter(tags=["tools"])


# Response models
class ToolInfoResponse(BaseModel):
    """Tool information response"""
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    category: str = Field(..., description="Tool category")
    required_authority_level: int = Field(..., description="Minimum authority level required")
    requires_approval: bool = Field(..., description="Whether tool requires approval")
    is_implemented: bool = Field(..., description="Whether tool is implemented")


class ToolListResponse(BaseModel):
    """Tool list response"""
    tools: List[ToolInfoResponse] = Field(..., description="List of tools")
    total: int = Field(..., description="Total number of tools")
    implemented: int = Field(..., description="Number of implemented tools")
    unimplemented: int = Field(..., description="Number of unimplemented tools")


class ToolCategoryResponse(BaseModel):
    """Tool category response"""
    name: str = Field(..., description="Category name")
    tools: List[ToolInfoResponse] = Field(..., description="Tools in category")
    total: int = Field(..., description="Total tools in category")
    implemented: int = Field(..., description="Implemented tools in category")
    unimplemented: int = Field(..., description="Unimplemented tools in category")


class ToolStatsResponse(BaseModel):
    """Tool registry statistics"""
    total_required: int = Field(..., description="Total required tools")
    total_registered: int = Field(..., description="Total registered tools")
    implemented: int = Field(..., description="Implemented tools")
    unimplemented: int = Field(..., description="Unimplemented tools")
    completion_percentage: float = Field(..., description="Completion percentage")
    by_category: Dict[str, Dict[str, int]] = Field(..., description="Stats by category")


class ToolValidationResponse(BaseModel):
    """Tool validation response"""
    is_complete: bool = Field(..., description="Whether all tools are implemented")
    total_required: int = Field(..., description="Total required tools")
    total_registered: int = Field(..., description="Total registered tools")
    total_implemented: int = Field(..., description="Total implemented tools")
    missing_tools: List[Dict[str, str]] = Field(..., description="Missing tools")
    placeholder_tools: List[Dict[str, str]] = Field(..., description="Placeholder tools")


class CategoryListResponse(BaseModel):
    """Category list response"""
    categories: List[str] = Field(..., description="List of category names")
    total: int = Field(..., description="Total number of categories")


# Helper functions
def _metadata_to_response(metadata: ToolMetadata) -> ToolInfoResponse:
    """Convert ToolMetadata to ToolInfoResponse"""
    return ToolInfoResponse(
        name=metadata.name,
        description=metadata.description,
        category=metadata.category,
        required_authority_level=metadata.required_authority_level,
        requires_approval=metadata.requires_approval,
        is_implemented=metadata.is_implemented,
    )


# API endpoints
@router.get("/tools", response_model=ToolListResponse)
async def list_all_tools(
    category: Optional[str] = None,
    only_implemented: bool = False,
    max_authority: Optional[int] = None,
) -> ToolListResponse:
    """
    List all registered tools.

    Args:
        category: Optional category filter
        only_implemented: Only return implemented tools
        max_authority: Only return tools available at this authority level (0-10)

    Returns:
        List of tools with statistics
    """
    registry = get_registry()

    # Convert max_authority to AuthorityLevel if provided
    authority_level = None
    if max_authority is not None:
        try:
            authority_level = AuthorityLevel(max_authority)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid authority level: {max_authority}. Must be 0-10."
            )

    # Get tools based on filters
    if category:
        if category not in registry.get_categories():
            raise HTTPException(
                status_code=404,
                detail=f"Category not found: {category}"
            )
        tools = registry.list_by_category(category)
    elif authority_level is not None:
        tools = registry.list_by_authority(authority_level)
    else:
        tools = registry.list_all()

    # Apply implemented filter
    if only_implemented:
        tools = [t for t in tools if t.is_implemented]

    # Convert to response
    tool_responses = [_metadata_to_response(t) for t in tools]

    return ToolListResponse(
        tools=tool_responses,
        total=len(tool_responses),
        implemented=len([t for t in tools if t.is_implemented]),
        unimplemented=len([t for t in tools if not t.is_implemented]),
    )


@router.get("/tools/categories", response_model=CategoryListResponse)
async def list_categories() -> CategoryListResponse:
    """
    List all tool categories.

    Returns:
        List of category names
    """
    registry = get_registry()
    categories = registry.get_categories()

    return CategoryListResponse(
        categories=categories,
        total=len(categories),
    )


@router.get("/tools/category/{category_name}", response_model=ToolCategoryResponse)
async def get_category_tools(category_name: str) -> ToolCategoryResponse:
    """
    Get all tools in a specific category.

    Args:
        category_name: Category name

    Returns:
        Tools in category with statistics
    """
    registry = get_registry()

    if category_name not in registry.get_categories():
        raise HTTPException(
            status_code=404,
            detail=f"Category not found: {category_name}"
        )

    tools = registry.list_by_category(category_name)
    tool_responses = [_metadata_to_response(t) for t in tools]

    return ToolCategoryResponse(
        name=category_name,
        tools=tool_responses,
        total=len(tools),
        implemented=len([t for t in tools if t.is_implemented]),
        unimplemented=len([t for t in tools if not t.is_implemented]),
    )


@router.get("/tools/stats", response_model=ToolStatsResponse)
async def get_tool_stats() -> ToolStatsResponse:
    """
    Get tool registry statistics.

    Returns:
        Registry statistics including totals, completion percentage, and breakdown by category
    """
    registry = get_registry()
    stats = registry.get_stats()

    return ToolStatsResponse(**stats)


@router.get("/tools/validate", response_model=ToolValidationResponse)
async def validate_tool_completeness() -> ToolValidationResponse:
    """
    Validate that all required tools are implemented.

    Returns:
        Validation results showing missing and placeholder tools
    """
    registry = get_registry()
    validation = registry.validate_completeness()

    return ToolValidationResponse(**validation)


@router.post("/tools/{tool_name}/check")
async def check_tool_available(
    tool_name: str,
    authority_level: int = 1,
) -> Dict[str, Any]:
    """
    Check if a tool is available for use at specified authority level.

    Args:
        tool_name: Tool name
        authority_level: Authority level (0-10)

    Returns:
        Availability status and reason
    """
    registry = get_registry()
    metadata = registry.get_metadata(tool_name)

    if not metadata:
        return {
            "available": False,
            "reason": f"Tool not found: {tool_name}",
            "tool_name": tool_name,
        }

    if not metadata.is_implemented:
        return {
            "available": False,
            "reason": f"Tool {tool_name} is not yet implemented",
            "tool_name": tool_name,
            "is_implemented": False,
        }

    if metadata.required_authority_level > authority_level:
        return {
            "available": False,
            "reason": f"Tool {tool_name} requires authority level {metadata.required_authority_level}, but only {authority_level} provided",
            "tool_name": tool_name,
            "required_authority": metadata.required_authority_level,
            "provided_authority": authority_level,
        }

    return {
        "available": True,
        "tool_name": tool_name,
        "description": metadata.description,
        "category": metadata.category,
        "requires_approval": metadata.requires_approval,
    }


@router.get("/tools/{tool_name}", response_model=ToolInfoResponse)
async def get_tool_info(tool_name: str) -> ToolInfoResponse:
    """
    Get information about a specific tool.

    Args:
        tool_name: Tool name

    Returns:
        Tool information
    """
    registry = get_registry()
    metadata = registry.get_metadata(tool_name)

    if not metadata:
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}"
        )

    return _metadata_to_response(metadata)
