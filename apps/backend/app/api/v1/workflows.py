"""
JARV Backend - Workflow API Endpoints

API endpoints for orchestrated multi-agent workflows.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.workflows.coding_loop import run_coding_loop, LoopStatus
from app.core.database import get_db
from app.core.auth import get_current_user

router = APIRouter(prefix="/workflows", tags=["workflows"])


class CodingLoopRequest(BaseModel):
    """Request to start a coding debug build loop"""
    task: str = Field(..., description="Coding task description")
    language: str = Field(..., description="Programming language")
    requirements: str = Field(default="", description="Specific requirements")
    existing_files: List[str] = Field(default_factory=list, description="Files to modify")
    workspace_id: str = Field(..., description="Workspace ID")
    max_iterations: int = Field(default=5, ge=1, le=10, description="Maximum iterations")
    quality_threshold: float = Field(default=80.0, ge=0, le=100, description="Quality threshold")
    coverage_threshold: float = Field(default=75.0, ge=0, le=100, description="Coverage threshold")


class IterationInfo(BaseModel):
    """Information about a single iteration"""
    iteration_number: int
    agent_used: str
    action_taken: str
    result: dict
    errors: List[str]
    success: bool


class CodingLoopResponse(BaseModel):
    """Response from coding loop"""
    status: str
    total_iterations: int
    final_code_quality: float
    test_coverage: float
    errors_fixed: int
    iterations: List[IterationInfo]
    final_output: dict
    message: str


@router.post("/coding-loop", response_model=CodingLoopResponse)
async def start_coding_loop(
    request: CodingLoopRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Start a coding debug build loop.

    This workflow orchestrates multiple specialist agents to:
    1. Generate/modify code
    2. Check for build errors
    3. Debug and fix issues
    4. Run tests
    5. Verify quality
    6. Iterate until success or max iterations

    Requires authentication and appropriate workspace permissions.
    """
    try:
        # Generate session ID
        session_id = f"coding_loop_{request.workspace_id}_{current_user.id}"

        # Run the coding loop
        result = await run_coding_loop(
            task=request.task,
            language=request.language,
            workspace_id=request.workspace_id,
            session_id=session_id,
            requirements=request.requirements,
            existing_files=request.existing_files,
            max_iterations=request.max_iterations,
            quality_threshold=request.quality_threshold,
            coverage_threshold=request.coverage_threshold,
        )

        # Convert iterations to response format
        iterations_response = [
            IterationInfo(
                iteration_number=it.iteration_number,
                agent_used=it.agent_used,
                action_taken=it.action_taken,
                result=it.result,
                errors=it.errors,
                success=it.success,
            )
            for it in result.iterations
        ]

        # Generate status message
        if result.status == LoopStatus.SUCCESS:
            message = (
                f"Coding loop succeeded after {result.total_iterations} iterations. "
                f"Quality: {result.final_code_quality}%, Coverage: {result.test_coverage}%"
            )
        elif result.status == LoopStatus.MAX_ITERATIONS:
            message = (
                f"Maximum iterations ({result.total_iterations}) reached. "
                f"Quality: {result.final_code_quality}%, Coverage: {result.test_coverage}%. "
                f"Fixed {result.errors_fixed} errors."
            )
        else:
            message = f"Coding loop failed with status: {result.status}"

        return CodingLoopResponse(
            status=result.status.value,
            total_iterations=result.total_iterations,
            final_code_quality=result.final_code_quality,
            test_coverage=result.test_coverage,
            errors_fixed=result.errors_fixed,
            iterations=iterations_response,
            final_output=result.final_output,
            message=message,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Coding loop failed: {str(e)}",
        )


@router.get("/coding-loop/status")
async def get_workflow_status(
    current_user = Depends(get_current_user),
):
    """
    Get status of workflow system.

    Returns information about available workflows and their status.
    """
    return {
        "workflows_available": [
            {
                "name": "coding-loop",
                "description": "Automated coding debug build loop",
                "agents_used": ["coding_agent", "debugging_agent", "qa", "verifier"],
                "status": "operational",
            },
        ],
        "total_workflows": 1,
    }
