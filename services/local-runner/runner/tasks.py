"""
JARV Local Runner - Task Manager

Manages background tasks with status tracking and cancellation.
"""
from typing import Optional, Dict, Any, List, AsyncIterator
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskManager:
    """
    Manages background tasks.

    Tracks task status, logs, and provides cancellation.
    """

    def __init__(self):
        """Initialize task manager"""
        self.logger = logging.getLogger("runner.tasks")
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.task_futures: Dict[str, asyncio.Task] = {}

    async def create_task(
        self,
        operation: str,
        **kwargs
    ) -> UUID:
        """
        Create task.

        Args:
            operation: Operation type
            **kwargs: Task parameters

        Returns:
            Task ID
        """
        task_id = uuid4()

        self.tasks[str(task_id)] = {
            "id": str(task_id),
            "operation": operation,
            "status": TaskStatus.PENDING,
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
            "logs": [],
            **kwargs
        }

        self.logger.info(f"Created task: {task_id}")
        return task_id

    async def start_task(self, task_id: str):
        """Mark task as started"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = TaskStatus.RUNNING
            self.tasks[task_id]["started_at"] = datetime.utcnow().isoformat()

    async def complete_task(self, task_id: str, result: Dict[str, Any]):
        """
        Mark task as completed.

        Args:
            task_id: Task ID
            result: Task result
        """
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = TaskStatus.COMPLETED
            self.tasks[task_id]["completed_at"] = datetime.utcnow().isoformat()
            self.tasks[task_id]["result"] = result
            self.logger.info(f"Task completed: {task_id}")

    async def fail_task(self, task_id: str, error: str):
        """
        Mark task as failed.

        Args:
            task_id: Task ID
            error: Error message
        """
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = TaskStatus.FAILED
            self.tasks[task_id]["completed_at"] = datetime.utcnow().isoformat()
            self.tasks[task_id]["error"] = error
            self.logger.error(f"Task failed: {task_id} - {error}")

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel running task.

        Args:
            task_id: Task ID

        Returns:
            True if cancelled, False if not found or already completed
        """
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        if task["status"] not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
            return False

        # Cancel future if exists
        if task_id in self.task_futures:
            self.task_futures[task_id].cancel()
            del self.task_futures[task_id]

        task["status"] = TaskStatus.CANCELLED
        task["completed_at"] = datetime.utcnow().isoformat()
        self.logger.info(f"Task cancelled: {task_id}")
        return True

    async def cancel_all_tasks(self):
        """Cancel all running tasks"""
        for task_id, task in list(self.tasks.items()):
            if task["status"] in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                await self.cancel_task(task_id)

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task status.

        Args:
            task_id: Task ID

        Returns:
            Task info or None
        """
        return self.tasks.get(task_id)

    async def get_task_logs(self, task_id: str) -> Optional[List[str]]:
        """
        Get task logs.

        Args:
            task_id: Task ID

        Returns:
            Log lines or None
        """
        if task_id not in self.tasks:
            return None

        return self.tasks[task_id].get("logs", [])

    async def append_task_log(self, task_id: str, log_line: str):
        """
        Append log line to task.

        Args:
            task_id: Task ID
            log_line: Log line to append
        """
        if task_id in self.tasks:
            self.tasks[task_id]["logs"].append({
                "timestamp": datetime.utcnow().isoformat(),
                "line": log_line,
            })

    async def stream_task_logs(self, task_id: str) -> AsyncIterator[str]:
        """
        Stream task logs.

        Args:
            task_id: Task ID

        Yields:
            Log lines
        """
        if task_id not in self.tasks:
            return

        # Send existing logs
        for log in self.tasks[task_id].get("logs", []):
            yield json.dumps(log)

        # Stream new logs (placeholder - in production would use pub/sub)
        # For now just indicate end of stream
        yield json.dumps({"status": "streaming_complete"})

    async def list_tasks(
        self,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List tasks.

        Args:
            status: Filter by status

        Returns:
            List of tasks
        """
        tasks = list(self.tasks.values())

        if status:
            tasks = [t for t in tasks if t["status"] == status]

        return tasks

    def active_task_count(self) -> int:
        """Get count of active tasks"""
        return sum(
            1 for task in self.tasks.values()
            if task["status"] in [TaskStatus.PENDING, TaskStatus.RUNNING]
        )
