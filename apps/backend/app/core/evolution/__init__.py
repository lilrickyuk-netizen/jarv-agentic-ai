"""
JARV Backend - Self-Evolution Layer

Enables JARV to improve itself from experience with safety guards.
"""
from app.core.evolution.experience import (
    ExperienceRecord,
    ExperienceCreate,
    ExperienceResult,
    ExperienceManager,
    capture_experience,
    summarize_experience,
    extract_lesson,
)
from app.core.evolution.improvements import (
    ImprovementType,
    ImprovementProposal,
    ImprovementCreate,
    ImprovementResult,
    RiskLevel,
    ImprovementManager,
    propose_rule_improvement,
    propose_runbook_improvement,
    propose_agent_improvement,
    propose_tool_improvement,
    propose_swarm_improvement,
    propose_plan_improvement,
)
from app.core.evolution.verification import (
    VerificationResult,
    VerificationManager,
    verify_improvement,
    approve_improvement,
    reject_improvement,
)
from app.core.evolution.versioning import (
    EvolutionVersion,
    VersionManager,
    create_version,
    rollback_version,
)

__all__ = [
    # Experience
    "ExperienceRecord",
    "ExperienceCreate",
    "ExperienceResult",
    "ExperienceManager",
    "capture_experience",
    "summarize_experience",
    "extract_lesson",
    # Improvements
    "ImprovementType",
    "ImprovementProposal",
    "ImprovementCreate",
    "ImprovementResult",
    "RiskLevel",
    "ImprovementManager",
    "propose_rule_improvement",
    "propose_runbook_improvement",
    "propose_agent_improvement",
    "propose_tool_improvement",
    "propose_swarm_improvement",
    "propose_plan_improvement",
    # Verification
    "VerificationResult",
    "VerificationManager",
    "verify_improvement",
    "approve_improvement",
    "reject_improvement",
    # Versioning
    "EvolutionVersion",
    "VersionManager",
    "create_version",
    "rollback_version",
]
