"""
JARV Local Runner - Audit Logger

Local audit logging for all runner operations.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
import json
import logging

from runner.config import settings

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Logs all local runner operations.

    Maintains local audit log for security and debugging.
    """

    def __init__(self):
        """Initialize audit logger"""
        self.logger = logging.getLogger("runner.audit")
        self.log_file = Path.home() / ".jarv" / "runner_audit.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    async def log_operation(
        self,
        operation: str,
        success: Optional[bool] = None,
        **kwargs
    ):
        """
        Log operation to audit log.

        Args:
            operation: Operation type
            success: Success status (None if in progress)
            **kwargs: Additional operation details
        """
        if not settings.AUDIT_ENABLED:
            return

        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "operation": operation,
                "success": success,
                **kwargs
            }

            # Append to log file
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

            # Also log to standard logger
            if success is None:
                self.logger.info(f"Operation started: {operation}")
            elif success:
                self.logger.info(f"Operation succeeded: {operation}")
            else:
                self.logger.warning(f"Operation failed: {operation}")

        except Exception as e:
            self.logger.error(f"Failed to write audit log: {e}")

    async def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent audit logs.

        Args:
            limit: Maximum number of logs to return

        Returns:
            List of log entries
        """
        if not self.log_file.exists():
            return []

        try:
            logs = []
            with open(self.log_file, 'r') as f:
                # Read last N lines
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        logs.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue

            return logs

        except Exception as e:
            self.logger.error(f"Failed to read audit logs: {e}")
            return []

    async def clear_logs(self):
        """Clear audit logs"""
        if self.log_file.exists():
            self.log_file.unlink()
            self.logger.info("Audit logs cleared")
