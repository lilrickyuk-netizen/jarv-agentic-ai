"""
JARV Backend - Safety Detector

Detects safety boundary violations and unsafe patterns.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
import logging
import re

logger = logging.getLogger(__name__)


class ViolationType(str, Enum):
    """Types of boundary violations"""
    AUTHORITY_EXCEEDED = "authority_exceeded"
    UNSAFE_OPERATION = "unsafe_operation"
    DATA_EXPOSURE = "data_exposure"
    RESOURCE_ABUSE = "resource_abuse"
    POLICY_VIOLATION = "policy_violation"
    RATE_LIMIT = "rate_limit"
    FINANCIAL_THRESHOLD = "financial_threshold"
    DESTRUCTIVE_ACTION = "destructive_action"
    UNAPPROVED_ACTION = "unapproved_action"
    SUSPICIOUS_PATTERN = "suspicious_pattern"


class ViolationSeverity(str, Enum):
    """Severity levels for violations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BoundaryViolation(BaseModel):
    """Record of a boundary violation"""
    violation_id: UUID = Field(default_factory=uuid4)
    type: ViolationType
    severity: ViolationSeverity
    description: str
    agent_name: Optional[str] = None
    user_id: Optional[UUID] = None
    workspace_id: Optional[UUID] = None
    tool_name: Optional[str] = None
    action: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolution_action: Optional[str] = None
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SafetyDetector:
    """
    Detects safety boundary violations.

    Monitors agent/tool actions and detects when safety boundaries are crossed.
    """

    def __init__(self):
        """Initialize safety detector"""
        self.logger = logging.getLogger("safety.detector")

        # Patterns for detecting sensitive data
        self.sensitive_patterns = {
            "api_key": re.compile(r"(?i)(api[_-]?key|apikey)[\s:=]+['\"]?([a-zA-Z0-9_-]{20,})['\"]?"),
            "password": re.compile(r"(?i)(password|passwd|pwd)[\s:=]+['\"]?([^\s'\"]{8,})['\"]?"),
            "token": re.compile(r"(?i)(token|bearer)[\s:=]+['\"]?([a-zA-Z0-9_.-]{20,})['\"]?"),
            "private_key": re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
            "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
            "credit_card": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
        }

        # Dangerous commands/patterns
        self.dangerous_patterns = [
            r"rm\s+-rf\s+/",
            r"DROP\s+DATABASE",
            r"DELETE\s+FROM\s+\w+\s+WHERE\s+1\s*=\s*1",
            r"FORMAT\s+C:",
            r"del\s+/s\s+/q\s+C:\\",
        ]

    def check_authority_violation(
        self,
        current_level: int,
        required_level: int,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryViolation]:
        """
        Check if action violates authority boundaries.

        Args:
            current_level: Current authority level
            required_level: Required authority level
            action: Action being attempted
            context: Additional context

        Returns:
            BoundaryViolation if authority exceeded, None otherwise
        """
        if current_level < required_level:
            severity = ViolationSeverity.MEDIUM
            if required_level - current_level >= 3:
                severity = ViolationSeverity.HIGH
            if required_level >= 8:  # Financial/critical operations
                severity = ViolationSeverity.CRITICAL

            violation = BoundaryViolation(
                type=ViolationType.AUTHORITY_EXCEEDED,
                severity=severity,
                description=f"Authority level {current_level} insufficient for action requiring level {required_level}",
                action=action,
                context=context or {},
                metadata={
                    "current_level": current_level,
                    "required_level": required_level,
                    "difference": required_level - current_level,
                }
            )

            self.logger.warning(
                f"Authority violation detected: {action}",
                extra=violation.dict()
            )

            return violation

        return None

    def check_data_exposure(
        self,
        data: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[BoundaryViolation]:
        """
        Check if data contains sensitive information that shouldn't be exposed.

        Args:
            data: Data to check
            context: Additional context

        Returns:
            List of violations found
        """
        violations = []

        for pattern_name, pattern in self.sensitive_patterns.items():
            matches = pattern.findall(data)
            if matches:
                violation = BoundaryViolation(
                    type=ViolationType.DATA_EXPOSURE,
                    severity=ViolationSeverity.HIGH,
                    description=f"Potential {pattern_name} exposure detected",
                    context=context or {},
                    metadata={
                        "pattern_type": pattern_name,
                        "matches_count": len(matches),
                        "data_sample": data[:100],  # First 100 chars only
                    }
                )
                violations.append(violation)

                self.logger.warning(
                    f"Data exposure detected: {pattern_name}",
                    extra={"pattern": pattern_name, "context": context}
                )

        return violations

    def check_dangerous_operation(
        self,
        command: str,
        tool_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryViolation]:
        """
        Check if operation is dangerous/destructive.

        Args:
            command: Command or operation to check
            tool_name: Tool executing the command
            context: Additional context

        Returns:
            BoundaryViolation if dangerous, None otherwise
        """
        for pattern in self.dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                violation = BoundaryViolation(
                    type=ViolationType.DESTRUCTIVE_ACTION,
                    severity=ViolationSeverity.CRITICAL,
                    description=f"Dangerous operation detected: matches pattern {pattern}",
                    tool_name=tool_name,
                    action=command[:100],  # First 100 chars
                    context=context or {},
                    metadata={
                        "matched_pattern": pattern,
                        "full_command_length": len(command),
                    }
                )

                self.logger.critical(
                    f"Dangerous operation detected",
                    extra=violation.dict()
                )

                return violation

        return None

    def check_rate_limit(
        self,
        user_id: UUID,
        action_type: str,
        limit: int,
        window_minutes: int = 60,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryViolation]:
        """
        Check if action exceeds rate limits.

        In production: Track action counts in Redis with expiring keys.

        Args:
            user_id: User performing action
            action_type: Type of action
            limit: Maximum actions allowed in window
            window_minutes: Time window in minutes
            context: Additional context

        Returns:
            BoundaryViolation if rate exceeded, None otherwise
        """
        # In production: Check Redis for action count
        # from app.core.redis import get_redis
        # redis = get_redis()
        # key = f"rate_limit:{user_id}:{action_type}"
        # count = await redis.incr(key)
        # if count == 1:
        #     await redis.expire(key, window_minutes * 60)
        #
        # if count > limit:
        #     return BoundaryViolation(...)

        # Placeholder: always pass for now
        return None

    def check_financial_threshold(
        self,
        amount: float,
        threshold: float,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryViolation]:
        """
        Check if financial operation exceeds threshold.

        Args:
            amount: Transaction amount
            threshold: Maximum allowed amount
            action: Action description
            context: Additional context

        Returns:
            BoundaryViolation if threshold exceeded, None otherwise
        """
        if amount > threshold:
            violation = BoundaryViolation(
                type=ViolationType.FINANCIAL_THRESHOLD,
                severity=ViolationSeverity.HIGH if amount > threshold * 2 else ViolationSeverity.MEDIUM,
                description=f"Financial threshold exceeded: ${amount:.2f} > ${threshold:.2f}",
                action=action,
                context=context or {},
                metadata={
                    "amount": amount,
                    "threshold": threshold,
                    "excess": amount - threshold,
                    "excess_percentage": ((amount - threshold) / threshold) * 100,
                }
            )

            self.logger.warning(
                f"Financial threshold violation: ${amount:.2f} > ${threshold:.2f}",
                extra=violation.dict()
            )

            return violation

        return None

    def check_resource_usage(
        self,
        resource_type: str,
        current_usage: float,
        limit: float,
        unit: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryViolation]:
        """
        Check if resource usage exceeds limits.

        Args:
            resource_type: Type of resource (cpu, memory, tokens, etc.)
            current_usage: Current usage amount
            limit: Maximum allowed
            unit: Unit of measurement
            context: Additional context

        Returns:
            BoundaryViolation if limit exceeded, None otherwise
        """
        if current_usage > limit:
            # Calculate severity based on how much limit is exceeded
            excess_ratio = current_usage / limit
            if excess_ratio > 2.0:
                severity = ViolationSeverity.CRITICAL
            elif excess_ratio > 1.5:
                severity = ViolationSeverity.HIGH
            else:
                severity = ViolationSeverity.MEDIUM

            violation = BoundaryViolation(
                type=ViolationType.RESOURCE_ABUSE,
                severity=severity,
                description=f"Resource limit exceeded: {resource_type} usage {current_usage:.2f}{unit} > {limit:.2f}{unit}",
                context=context or {},
                metadata={
                    "resource_type": resource_type,
                    "current_usage": current_usage,
                    "limit": limit,
                    "unit": unit,
                    "excess_ratio": excess_ratio,
                }
            )

            self.logger.warning(
                f"Resource limit violation: {resource_type}",
                extra=violation.dict()
            )

            return violation

        return None

    def check_unapproved_action(
        self,
        action: str,
        requires_approval: bool,
        is_approved: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundaryViolation]:
        """
        Check if action requires approval but hasn't been approved.

        Args:
            action: Action description
            requires_approval: Whether action requires approval
            is_approved: Whether action has been approved
            context: Additional context

        Returns:
            BoundaryViolation if approval required but not granted, None otherwise
        """
        if requires_approval and not is_approved:
            violation = BoundaryViolation(
                type=ViolationType.UNAPPROVED_ACTION,
                severity=ViolationSeverity.HIGH,
                description=f"Action requires approval but not yet approved: {action}",
                action=action,
                context=context or {},
                metadata={
                    "requires_approval": True,
                    "is_approved": False,
                }
            )

            self.logger.warning(
                f"Unapproved action detected: {action}",
                extra=violation.dict()
            )

            return violation

        return None
