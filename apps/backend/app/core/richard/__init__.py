"""
JARV Backend - Richard Boundary Operator

Special oversight system for boundary management and guidance.

Named after Richard, this system provides authoritative boundary decisions
and guidance for complex or edge-case scenarios.
"""
from app.core.richard.operator import RichardOperator, RichardInput, RichardDecision
from app.core.richard.guidance import RichardGuidance, request_richard_guidance

__all__ = [
    "RichardOperator",
    "RichardInput",
    "RichardDecision",
    "RichardGuidance",
    "request_richard_guidance",
]
