"""
JARV Backend - Agent Management API

Endpoints for discovering and managing JARV agents.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
import logging

from app.core.agents import get_registry, AgentMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentInfo(BaseModel):
    """Information about a registered agent"""
    name: str
    role: str
    category: str
    description: str
    required_authority_level: int
    default_tools: List[str]
    is_implemented: bool


class AgentStats(BaseModel):
    """Agent registry statistics"""
    total_required: int
    total_registered: int
    implemented: int
    unimplemented: int
    completion_percentage: float
    by_category: Dict[str, Dict[str, int]]


class AgentValidation(BaseModel):
    """Agent registry validation results"""
    is_complete: bool
    total_required: int
    total_registered: int
    total_implemented: int
    missing_agents: List[Dict[str, str]]
    placeholder_agents: List[Dict[str, str]]


@router.get(
    "/list",
    response_model=List[AgentInfo],
    summary="List all agents",
    description="Get a list of all registered agents with their metadata"
)
async def list_all_agents(
    category: Optional[str] = None,
    only_implemented: bool = False,
) -> List[AgentInfo]:
    """
    List all registered agents.

    Args:
        category: Optional category filter (core, development, infrastructure, business, customer, financial, specialized)
        only_implemented: Only return implemented agents

    Returns:
        List of agent information
    """
    try:
        registry = get_registry()

        # Get agents
        if category:
            agents = registry.list_by_category(category)
        else:
            agents = registry.list_all()

        # Filter if needed
        if only_implemented:
            agents = [a for a in agents if a.is_implemented]

        # Convert to response model
        return [
            AgentInfo(
                name=agent.name,
                role=agent.role,
                category=agent.category,
                description=agent.description,
                required_authority_level=agent.required_authority_level,
                default_tools=agent.default_tools,
                is_implemented=agent.is_implemented,
            )
            for agent in agents
        ]

    except Exception as e:
        logger.error(f"Error listing agents: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents: {str(e)}"
        )


@router.get(
    "/categories",
    response_model=List[str],
    summary="List agent categories",
    description="Get list of all agent categories"
)
async def list_categories() -> List[str]:
    """
    List all agent categories.

    Returns:
        List of category names
    """
    try:
        registry = get_registry()
        return registry.get_categories()

    except Exception as e:
        logger.error(f"Error listing categories: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list categories: {str(e)}"
        )


@router.get(
    "/stats",
    response_model=AgentStats,
    summary="Get agent statistics",
    description="Get statistics about agent registry including completion percentage"
)
async def get_agent_stats() -> AgentStats:
    """
    Get agent registry statistics.

    Returns:
        Agent statistics including counts by category
    """
    try:
        registry = get_registry()
        stats = registry.get_stats()
        return AgentStats(**stats)

    except Exception as e:
        logger.error(f"Error getting agent stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent stats: {str(e)}"
        )


@router.get(
    "/validate",
    response_model=AgentValidation,
    summary="Validate agent completeness",
    description="Check if all 31 required agents are implemented"
)
async def validate_agents() -> AgentValidation:
    """
    Validate that all required agents are implemented.

    Returns:
        Validation results with missing and placeholder agents
    """
    try:
        registry = get_registry()
        validation = registry.validate_completeness()
        return AgentValidation(**validation)

    except Exception as e:
        logger.error(f"Error validating agents: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate agents: {str(e)}"
        )


@router.get(
    "/{agent_name}",
    response_model=AgentInfo,
    summary="Get agent details",
    description="Get detailed information about a specific agent"
)
async def get_agent_details(agent_name: str) -> AgentInfo:
    """
    Get details for a specific agent.

    Args:
        agent_name: Name of agent to retrieve

    Returns:
        Agent information

    Raises:
        404: If agent not found
    """
    try:
        registry = get_registry()
        metadata = registry.get_metadata(agent_name)

        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent '{agent_name}' not found in registry"
            )

        return AgentInfo(
            name=metadata.name,
            role=metadata.role,
            category=metadata.category,
            description=metadata.description,
            required_authority_level=metadata.required_authority_level,
            default_tools=metadata.default_tools,
            is_implemented=metadata.is_implemented,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent details: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent details: {str(e)}"
        )


@router.get(
    "/category/{category}",
    response_model=List[AgentInfo],
    summary="List agents by category",
    description="Get all agents in a specific category"
)
async def list_agents_by_category(
    category: str,
    only_implemented: bool = False,
) -> List[AgentInfo]:
    """
    List agents in a specific category.

    Args:
        category: Category name
        only_implemented: Only return implemented agents

    Returns:
        List of agents in category
    """
    try:
        registry = get_registry()

        # Check if category exists
        if category not in registry.get_categories():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category '{category}' not found"
            )

        agents = registry.list_by_category(category)

        # Filter if needed
        if only_implemented:
            agents = [a for a in agents if a.is_implemented]

        return [
            AgentInfo(
                name=agent.name,
                role=agent.role,
                category=agent.category,
                description=agent.description,
                required_authority_level=agent.required_authority_level,
                default_tools=agent.default_tools,
                is_implemented=agent.is_implemented,
            )
            for agent in agents
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing agents by category: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents by category: {str(e)}"
        )
