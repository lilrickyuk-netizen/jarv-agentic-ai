"""
JARV Backend - Spoken Status Replies

Generates spoken status replies for voice feedback.
"""
from typing import Dict, Any, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class StatusType(str, Enum):
    """Types of status messages"""
    SUCCESS = "success"
    ERROR = "error"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    COMPLETED = "completed"
    WARNING = "warning"
    INFO = "info"


class SpokenStatusReplies:
    """
    Generates spoken status replies for various system states.

    Provides natural language responses for:
    - Command success/failure
    - Task progress updates
    - System status
    - Error messages
    - Confirmations
    """

    def __init__(self, language: str = "en-US"):
        self.language = language
        self._status_templates = self._load_status_templates()

    def _load_status_templates(self) -> Dict[str, Dict[str, list]]:
        """Load status message templates"""
        return {
            "en-US": {
                StatusType.SUCCESS: [
                    "Done.",
                    "Command completed successfully.",
                    "Task finished.",
                    "All set.",
                    "Completed.",
                ],
                StatusType.ERROR: [
                    "I encountered an error.",
                    "Something went wrong.",
                    "I couldn't complete that task.",
                    "There was a problem.",
                    "An error occurred.",
                ],
                StatusType.IN_PROGRESS: [
                    "Working on it.",
                    "Processing your request.",
                    "This will take a moment.",
                    "In progress.",
                    "I'm on it.",
                ],
                StatusType.WAITING: [
                    "Waiting for approval.",
                    "This requires authorization.",
                    "Awaiting confirmation.",
                    "Needs approval to proceed.",
                ],
                StatusType.COMPLETED: [
                    "Task completed successfully.",
                    "All done.",
                    "Finished.",
                    "Complete.",
                ],
                StatusType.WARNING: [
                    "Warning:",
                    "Please note:",
                    "Heads up:",
                    "Important:",
                ],
                StatusType.INFO: [
                    "Information:",
                    "Here's what I found:",
                    "Let me tell you:",
                    "Just so you know:",
                ],
            },
            "es-ES": {
                StatusType.SUCCESS: [
                    "Hecho.",
                    "Comando completado exitosamente.",
                    "Tarea finalizada.",
                ],
                StatusType.ERROR: [
                    "Encontré un error.",
                    "Algo salió mal.",
                    "No pude completar esa tarea.",
                ],
            },
        }

    def get_status_reply(
        self,
        status_type: StatusType,
        details: Optional[str] = None,
        variant: int = 0,
    ) -> str:
        """
        Get a spoken status reply.

        Args:
            status_type: Type of status message
            details: Optional additional details
            variant: Template variant index

        Returns:
            Spoken status text
        """
        templates = self._status_templates.get(self.language, {}).get(status_type, ["Status update."])

        # Get template (wrap around if variant exceeds available templates)
        template_idx = variant % len(templates)
        base_message = templates[template_idx]

        # Add details if provided
        if details:
            return f"{base_message} {details}"
        return base_message

    def format_task_status(
        self,
        task_name: str,
        status: str,
        progress: Optional[int] = None,
    ) -> str:
        """
        Format task status for spoken reply.

        Args:
            task_name: Name of the task
            status: Current status
            progress: Progress percentage (0-100)

        Returns:
            Spoken status text
        """
        if progress is not None:
            return f"{task_name} is {progress}% complete. Status: {status}."
        return f"{task_name} status: {status}."

    def format_command_result(
        self,
        command: str,
        success: bool,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> str:
        """
        Format command result for spoken reply.

        Args:
            command: The executed command
            success: Whether command succeeded
            result: Result message
            error: Error message if failed

        Returns:
            Spoken result text
        """
        if success:
            base = self.get_status_reply(StatusType.SUCCESS)
            if result:
                return f"{base} {result}"
            return base
        else:
            base = self.get_status_reply(StatusType.ERROR)
            if error:
                return f"{base} {error}"
            return base

    def format_approval_request(
        self,
        action: str,
        authority_level: int,
    ) -> str:
        """
        Format approval request for spoken reply.

        Args:
            action: Action requiring approval
            authority_level: Required authority level

        Returns:
            Spoken approval request
        """
        return (
            f"{self.get_status_reply(StatusType.WAITING)} "
            f"The action '{action}' requires level {authority_level} authorization. "
            f"Please approve to proceed."
        )

    def format_system_status(
        self,
        system_name: str,
        is_healthy: bool,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Format system status for spoken reply.

        Args:
            system_name: Name of the system/service
            is_healthy: Whether system is healthy
            details: Optional status details

        Returns:
            Spoken system status
        """
        status = "operational" if is_healthy else "experiencing issues"
        base = f"{system_name} is {status}."

        if details:
            detail_str = ", ".join([f"{k}: {v}" for k, v in details.items()])
            return f"{base} {detail_str}."

        return base

    def format_agent_status(
        self,
        agent_name: str,
        current_task: Optional[str] = None,
        status: str = "idle",
    ) -> str:
        """
        Format agent status for spoken reply.

        Args:
            agent_name: Name of the agent
            current_task: Current task description
            status: Agent status

        Returns:
            Spoken agent status
        """
        if current_task:
            return f"{agent_name} is currently {status}, working on: {current_task}."
        return f"{agent_name} is {status}."

    def format_error_with_suggestion(
        self,
        error_message: str,
        suggestion: str,
    ) -> str:
        """
        Format error with suggestion for spoken reply.

        Args:
            error_message: The error message
            suggestion: Suggested action

        Returns:
            Spoken error with suggestion
        """
        return (
            f"{self.get_status_reply(StatusType.ERROR)} "
            f"{error_message}. "
            f"Suggestion: {suggestion}"
        )

    def format_multi_step_progress(
        self,
        current_step: int,
        total_steps: int,
        current_step_name: str,
    ) -> str:
        """
        Format multi-step progress for spoken reply.

        Args:
            current_step: Current step number (1-indexed)
            total_steps: Total number of steps
            current_step_name: Name of current step

        Returns:
            Spoken progress update
        """
        return (
            f"Step {current_step} of {total_steps}: {current_step_name}. "
            f"{self.get_status_reply(StatusType.IN_PROGRESS)}"
        )

    def get_confirmation_prompt(self, action: str) -> str:
        """
        Get confirmation prompt for risky action.

        Args:
            action: Action to confirm

        Returns:
            Spoken confirmation prompt
        """
        return f"Are you sure you want to {action}? Please confirm."

    def get_supported_languages(self) -> list[str]:
        """Get list of supported languages"""
        return list(self._status_templates.keys())
