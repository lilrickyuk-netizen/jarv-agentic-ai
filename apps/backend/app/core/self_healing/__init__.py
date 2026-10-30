"""
JARV Backend - Self-Healing System

Self-healing infrastructure that automatically detects, diagnoses, and fixes issues.
"""
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

__all__ = [
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
]
