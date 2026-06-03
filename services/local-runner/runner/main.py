"""
JARV Local Runner - Main Service

Secure local execution service for JARV backend.
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from typing import Optional
import logging
import asyncio
from datetime import datetime

from runner.config import settings
from runner.auth import verify_token
from runner.executor import CommandExecutor, FileExecutor
from runner.audit import AuditLogger
from runner.tasks import TaskManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Initialize managers
command_executor = CommandExecutor()
file_executor = FileExecutor()
audit_logger = AuditLogger()
task_manager = TaskManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting JARV Local Runner")
    logger.info(f"Allowed folders: {settings.ALLOWED_FOLDERS}")
    logger.info(f"Audit logging: {settings.AUDIT_ENABLED}")

    yield

    # Shutdown
    logger.info("Shutting down JARV Local Runner")
    await task_manager.cancel_all_tasks()


# Create FastAPI application
app = FastAPI(
    title="JARV Local Runner",
    description="Secure local execution service for JARV",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "JARV Local Runner",
        "version": "1.0.0",
        "status": "running",
        "allowed_folders": settings.ALLOWED_FOLDERS,
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_tasks": task_manager.active_task_count(),
    }


# =============================================================================
# FILE EXECUTION ENDPOINTS
# =============================================================================

@app.post("/files/read")
async def read_file(
    path: str,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """
    Read file from local filesystem.

    Requires authentication and path validation.
    """
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    try:
        # Audit log
        await audit_logger.log_operation(
            operation="file_read",
            path=path,
            success=None,
        )

        # Execute
        content = await file_executor.read_file(path)

        # Audit success
        await audit_logger.log_operation(
            operation="file_read",
            path=path,
            success=True,
        )

        return {
            "path": path,
            "content": content,
            "size": len(content),
        }

    except Exception as e:
        # Audit failure
        await audit_logger.log_operation(
            operation="file_read",
            path=path,
            success=False,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/files/write")
async def write_file(
    path: str,
    content: str,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """
    Write file to local filesystem.

    Requires authentication and path validation.
    """
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    try:
        # Audit log
        await audit_logger.log_operation(
            operation="file_write",
            path=path,
            success=None,
        )

        # Execute
        await file_executor.write_file(path, content)

        # Audit success
        await audit_logger.log_operation(
            operation="file_write",
            path=path,
            success=True,
        )

        return {
            "path": path,
            "written": True,
            "size": len(content),
        }

    except Exception as e:
        # Audit failure
        await audit_logger.log_operation(
            operation="file_write",
            path=path,
            success=False,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/files/list")
async def list_files(
    path: str,
    pattern: Optional[str] = None,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """
    List files in directory.

    Requires authentication and path validation.
    """
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    try:
        # Audit log
        await audit_logger.log_operation(
            operation="file_list",
            path=path,
            success=None,
        )

        # Execute
        files = await file_executor.list_files(path, pattern)

        # Audit success
        await audit_logger.log_operation(
            operation="file_list",
            path=path,
            success=True,
        )

        return {
            "path": path,
            "pattern": pattern,
            "files": files,
            "count": len(files),
        }

    except Exception as e:
        # Audit failure
        await audit_logger.log_operation(
            operation="file_list",
            path=path,
            success=False,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# COMMAND EXECUTION ENDPOINTS
# =============================================================================

@app.post("/commands/execute")
async def execute_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 300,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """
    Execute command on local system.

    Requires authentication and command validation.
    """
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    try:
        # Audit log
        await audit_logger.log_operation(
            operation="command_execute",
            command=command,
            success=None,
        )

        # Create task
        task_id = await task_manager.create_task(
            operation="command",
            command=command,
            cwd=cwd,
            timeout=timeout,
        )

        # Execute
        result = await command_executor.execute_command(
            command=command,
            cwd=cwd,
            timeout=timeout,
        )

        # Mark task complete
        await task_manager.complete_task(task_id, result)

        # Audit success
        await audit_logger.log_operation(
            operation="command_execute",
            command=command,
            success=True,
        )

        return {
            "task_id": str(task_id),
            "command": command,
            "exit_code": result.get("exit_code", 0),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "duration": result.get("duration", 0),
        }

    except Exception as e:
        # Audit failure
        await audit_logger.log_operation(
            operation="command_execute",
            command=command,
            success=False,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/commands/execute-background")
async def execute_command_background(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 3600,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """
    Execute command in background.

    Returns task_id for status checking.
    """
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    try:
        # Audit log
        await audit_logger.log_operation(
            operation="command_background",
            command=command,
            success=None,
        )

        # Create task
        task_id = await task_manager.create_task(
            operation="command_background",
            command=command,
            cwd=cwd,
            timeout=timeout,
        )

        # Start in background
        asyncio.create_task(
            command_executor.execute_command_background(
                task_id=task_id,
                command=command,
                cwd=cwd,
                timeout=timeout,
                task_manager=task_manager,
            )
        )

        return {
            "task_id": str(task_id),
            "command": command,
            "status": "started",
            "message": "Command started in background"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TASK MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/tasks/{task_id}/status")
async def get_task_status(
    task_id: str,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """Get task status"""
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    status = await task_manager.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")

    return status


@app.get("/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """Get task logs"""
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    logs = await task_manager.get_task_logs(task_id)
    if logs is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "logs": logs,
    }


@app.get("/tasks/{task_id}/stream")
async def stream_task_logs(
    task_id: str,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """Stream task logs in real-time"""
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    async def log_generator():
        """Generate log lines"""
        async for line in task_manager.stream_task_logs(task_id):
            yield f"data: {line}\n\n"

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
    )


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """Cancel running task"""
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    success = await task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or already completed")

    return {
        "task_id": task_id,
        "cancelled": True,
    }


@app.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """List tasks"""
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    tasks = await task_manager.list_tasks(status)
    return {
        "tasks": tasks,
        "count": len(tasks),
    }


# =============================================================================
# AUDIT LOG ENDPOINTS
# =============================================================================

@app.get("/audit/logs")
async def get_audit_logs(
    limit: int = 100,
    token: str = Header(..., alias="X-Runner-Token"),
):
    """Get audit logs"""
    # Verify token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    logs = await audit_logger.get_logs(limit)
    return {
        "logs": logs,
        "count": len(logs),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "runner.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )
