"""
JARV Backend - Task State Machine

State machine for task lifecycle management with 14 states and
controlled state transitions.
"""
from enum import Enum
from typing import Optional, List, Set, Dict
from datetime import datetime
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    """
    Task lifecycle states.

    Tasks flow through these states as they are executed by the system.
    Each state represents a specific point in the task lifecycle.
    """
    # Initial states
    CREATED = "created"                                    # Task just created, not yet planned
    PLANNED = "planned"                                    # Task plan created, not yet assigned
    ASSIGNED = "assigned"                                  # Task assigned to agent, not yet running

    # Execution states
    RUNNING = "running"                                    # Task actively executing

    # Waiting states (execution paused)
    WAITING_ON_TOOL = "waiting_on_tool"                   # Waiting for tool execution
    WAITING_ON_SWARM = "waiting_on_swarm"                 # Waiting for swarm completion
    WAITING_ON_APPROVAL = "waiting_on_approval"           # Waiting for approval
    WAITING_ON_RICHARD_BOUNDARY_INPUT = "waiting_on_richard_boundary_input"  # Waiting for user input

    # Recovery states
    RESUMING_FROM_CHECKPOINT = "resuming_from_checkpoint"  # Resuming from saved checkpoint

    # Verification states
    VERIFYING = "verifying"                               # Verifying results

    # Terminal states
    COMPLETE = "complete"                                  # Task completed successfully
    FAILED = "failed"                                      # Task failed with error
    BLOCKED = "blocked"                                    # Task blocked by dependency or issue
    CANCELLED = "cancelled"                                # Task cancelled by user

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state (cannot transition further)"""
        return self in {
            TaskState.COMPLETE,
            TaskState.FAILED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        }

    @property
    def is_waiting(self) -> bool:
        """Check if this is a waiting state (paused, not terminal)"""
        return self in {
            TaskState.WAITING_ON_TOOL,
            TaskState.WAITING_ON_SWARM,
            TaskState.WAITING_ON_APPROVAL,
            TaskState.WAITING_ON_RICHARD_BOUNDARY_INPUT,
        }

    @property
    def is_active(self) -> bool:
        """Check if this is an active execution state"""
        return self in {
            TaskState.RUNNING,
            TaskState.RESUMING_FROM_CHECKPOINT,
            TaskState.VERIFYING,
        }


@dataclass
class StateTransition:
    """Record of a state transition"""
    from_state: TaskState
    to_state: TaskState
    timestamp: datetime
    reason: Optional[str] = None
    metadata: Optional[Dict] = None


class TaskStateMachine:
    """
    State machine for task lifecycle management.

    Enforces valid state transitions and maintains transition history.
    Prevents invalid transitions and logs all state changes.
    """

    # Define allowed state transitions
    ALLOWED_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
        TaskState.CREATED: {
            TaskState.PLANNED,
            TaskState.CANCELLED,
            TaskState.FAILED,
        },
        TaskState.PLANNED: {
            TaskState.ASSIGNED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
            TaskState.FAILED,
        },
        TaskState.ASSIGNED: {
            TaskState.RUNNING,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
            TaskState.FAILED,
        },
        TaskState.RUNNING: {
            TaskState.WAITING_ON_TOOL,
            TaskState.WAITING_ON_SWARM,
            TaskState.WAITING_ON_APPROVAL,
            TaskState.WAITING_ON_RICHARD_BOUNDARY_INPUT,
            TaskState.VERIFYING,
            TaskState.COMPLETE,
            TaskState.FAILED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        },
        TaskState.WAITING_ON_TOOL: {
            TaskState.RUNNING,
            TaskState.FAILED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        },
        TaskState.WAITING_ON_SWARM: {
            TaskState.RUNNING,
            TaskState.FAILED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        },
        TaskState.WAITING_ON_APPROVAL: {
            TaskState.RUNNING,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        },
        TaskState.WAITING_ON_RICHARD_BOUNDARY_INPUT: {
            TaskState.RUNNING,
            TaskState.RESUMING_FROM_CHECKPOINT,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        },
        TaskState.RESUMING_FROM_CHECKPOINT: {
            TaskState.RUNNING,
            TaskState.FAILED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        },
        TaskState.VERIFYING: {
            TaskState.COMPLETE,
            TaskState.RUNNING,  # Can go back to running if verification fails
            TaskState.FAILED,
            TaskState.BLOCKED,
        },
        # Terminal states cannot transition further
        TaskState.COMPLETE: set(),
        TaskState.FAILED: set(),
        TaskState.BLOCKED: set(),
        TaskState.CANCELLED: set(),
    }

    def __init__(self, initial_state: TaskState = TaskState.CREATED):
        """
        Initialize state machine.

        Args:
            initial_state: Starting state (default: CREATED)
        """
        self.current_state = initial_state
        self.history: List[StateTransition] = [
            StateTransition(
                from_state=initial_state,
                to_state=initial_state,
                timestamp=datetime.utcnow(),
                reason="Initial state",
            )
        ]
        logger.debug(f"Task state machine initialized in state: {initial_state}")

    def transition(
        self,
        to_state: TaskState,
        reason: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Attempt to transition to a new state.

        Args:
            to_state: Target state
            reason: Reason for transition
            metadata: Additional metadata

        Returns:
            True if transition successful, False if invalid

        Raises:
            ValueError: If transition is not allowed
        """
        # Check if already in terminal state
        if self.current_state.is_terminal:
            raise ValueError(
                f"Cannot transition from terminal state {self.current_state}"
            )

        # Check if transition is allowed
        if not self.can_transition(to_state):
            raise ValueError(
                f"Invalid transition from {self.current_state} to {to_state}. "
                f"Allowed transitions: {self.get_allowed_transitions()}"
            )

        # Record transition
        transition = StateTransition(
            from_state=self.current_state,
            to_state=to_state,
            timestamp=datetime.utcnow(),
            reason=reason,
            metadata=metadata,
        )
        self.history.append(transition)

        # Update state
        old_state = self.current_state
        self.current_state = to_state

        logger.info(
            f"Task state transition: {old_state} → {to_state}",
            extra={
                "from_state": old_state.value,
                "to_state": to_state.value,
                "reason": reason,
            }
        )

        return True

    def can_transition(self, to_state: TaskState) -> bool:
        """
        Check if transition to target state is allowed.

        Args:
            to_state: Target state

        Returns:
            True if transition is allowed
        """
        allowed = self.ALLOWED_TRANSITIONS.get(self.current_state, set())
        return to_state in allowed

    def get_allowed_transitions(self) -> Set[TaskState]:
        """
        Get set of states that can be transitioned to from current state.

        Returns:
            Set of allowed target states
        """
        return self.ALLOWED_TRANSITIONS.get(self.current_state, set())

    def get_history(self) -> List[StateTransition]:
        """
        Get complete transition history.

        Returns:
            List of all transitions
        """
        return self.history.copy()

    def get_state(self) -> TaskState:
        """
        Get current state.

        Returns:
            Current task state
        """
        return self.current_state

    def is_terminal(self) -> bool:
        """
        Check if current state is terminal.

        Returns:
            True if in terminal state
        """
        return self.current_state.is_terminal

    def is_waiting(self) -> bool:
        """
        Check if current state is a waiting state.

        Returns:
            True if waiting
        """
        return self.current_state.is_waiting

    def is_active(self) -> bool:
        """
        Check if current state is active execution.

        Returns:
            True if actively executing
        """
        return self.current_state.is_active

    def get_duration_in_state(self) -> float:
        """
        Get duration in current state in seconds.

        Returns:
            Seconds since last transition
        """
        if not self.history:
            return 0.0

        last_transition = self.history[-1]
        duration = (datetime.utcnow() - last_transition.timestamp).total_seconds()
        return duration

    def to_dict(self) -> Dict:
        """
        Convert state machine to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            "current_state": self.current_state.value,
            "is_terminal": self.is_terminal(),
            "is_waiting": self.is_waiting(),
            "is_active": self.is_active(),
            "duration_in_state": self.get_duration_in_state(),
            "allowed_transitions": [s.value for s in self.get_allowed_transitions()],
            "history": [
                {
                    "from_state": t.from_state.value,
                    "to_state": t.to_state.value,
                    "timestamp": t.timestamp.isoformat(),
                    "reason": t.reason,
                    "metadata": t.metadata,
                }
                for t in self.history
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TaskStateMachine":
        """
        Reconstruct state machine from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            Reconstructed state machine
        """
        current_state = TaskState(data["current_state"])
        machine = cls(initial_state=current_state)

        # Reconstruct history
        machine.history = [
            StateTransition(
                from_state=TaskState(t["from_state"]),
                to_state=TaskState(t["to_state"]),
                timestamp=datetime.fromisoformat(t["timestamp"]),
                reason=t.get("reason"),
                metadata=t.get("metadata"),
            )
            for t in data["history"]
        ]

        return machine


# ===== Helper Functions =====

def create_state_machine() -> TaskStateMachine:
    """
    Create a new task state machine in CREATED state.

    Returns:
        New state machine
    """
    return TaskStateMachine(initial_state=TaskState.CREATED)


def get_all_states() -> List[TaskState]:
    """
    Get list of all task states.

    Returns:
        List of all states
    """
    return list(TaskState)


def get_terminal_states() -> List[TaskState]:
    """
    Get list of terminal states.

    Returns:
        List of terminal states
    """
    return [s for s in TaskState if s.is_terminal]


def get_waiting_states() -> List[TaskState]:
    """
    Get list of waiting states.

    Returns:
        List of waiting states
    """
    return [s for s in TaskState if s.is_waiting]


def get_active_states() -> List[TaskState]:
    """
    Get list of active execution states.

    Returns:
        List of active states
    """
    return [s for s in TaskState if s.is_active]


def validate_state_transition(from_state: TaskState, to_state: TaskState) -> bool:
    """
    Validate if a state transition is allowed.

    Args:
        from_state: Current state
        to_state: Target state

    Returns:
        True if transition is allowed
    """
    allowed = TaskStateMachine.ALLOWED_TRANSITIONS.get(from_state, set())
    return to_state in allowed
