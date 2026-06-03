"""
JARV Backend - Self-Healing System

Self-healing infrastructure that automatically detects, diagnoses, and fixes issues.
"""
from .monitoring import MonitoringService, HealthCheckMonitor, LogMonitor, ErrorMonitor
from .runbooks import (
    RunbookBase,
    WebsiteDownRunbook,
    APIErrorSpikeRunbook,
    QueueStuckRunbook,
    PaymentWebhookRunbook,
    BugReportsIncreasingRunbook,
    ServerPressureRunbook,
    SSLDomainRunbook,
    IntegrationRequiredError,
)
from .workflows import (
    SelfHealingWorkflow,
    RollbackWorkflow,
    IncidentMemoryWorkflow,
    ExperienceRecordWorkflow,
)

__all__ = [
    # Monitoring
    "MonitoringService",
    "HealthCheckMonitor",
    "LogMonitor",
    "ErrorMonitor",
    # Runbooks
    "RunbookBase",
    "WebsiteDownRunbook",
    "APIErrorSpikeRunbook",
    "QueueStuckRunbook",
    "PaymentWebhookRunbook",
    "BugReportsIncreasingRunbook",
    "ServerPressureRunbook",
    "SSLDomainRunbook",
    "IntegrationRequiredError",
    # Workflows
    "SelfHealingWorkflow",
    "RollbackWorkflow",
    "IncidentMemoryWorkflow",
    "ExperienceRecordWorkflow",
]
