"""
JARV Backend - Self-Evolution Layer

Enables JARV to improve itself from experience with safety guards:
experience capture (experience.py, backed by the verified-learning service)
and persisted, verified, reversible changes to workspace rules, runbooks,
agent instructions, tool selection, operating plans and swarm strategy
(engine.py).
"""
from app.core.evolution.engine import EvolutionEngine, evolution_engine
from app.core.evolution.experience import (
    ExperienceCreate,
    ExperienceManager,
    ExperienceResult,
    LessonExtract,
)

__all__ = [
    "EvolutionEngine",
    "evolution_engine",
    "ExperienceCreate",
    "ExperienceResult",
    "ExperienceManager",
    "LessonExtract",
]
