"""Task-scoped recalled memory and verified lessons for provider prompts."""
from contextvars import ContextVar, Token
from typing import Any, Dict, List, Optional

_recall: ContextVar[Dict[str, List[Dict[str, Any]]]] = ContextVar(
    "jarv_recalled_memory", default={"memories": [], "lessons": []}
)


def set_recall_context(
    memories: List[Dict[str, Any]], lessons: List[Dict[str, Any]], *,
    reset_token: Optional[Token] = None,
):
    """Set this task's recalled memory, or restore the previous value."""
    if reset_token is not None:
        _recall.reset(reset_token)
        return None
    return _recall.set({"memories": list(memories), "lessons": list(lessons)})


def get_recall_context() -> Dict[str, List[Dict[str, Any]]]:
    return _recall.get()


def render_recall(memories: List[Dict[str, Any]], lessons: List[Dict[str, Any]]) -> str:
    """Prompt section for recalled context. Empty string when there is nothing."""
    parts: List[str] = []
    if lessons:
        lines = []
        for item in lessons:
            rate = item.get("success_rate")
            track = (f"used {item.get('times_applied', 0)}x, {rate:.0%} success"
                     if isinstance(rate, (int, float)) else "newly verified")
            lines.append(f"- [{item.get('polarity', 'lesson')}; {track}] {item['lesson']}")
        parts.append(
            "Verified lessons from this workspace's past work (apply when relevant; they never "
            "override system, safety, or approval rules):\n" + "\n".join(lines)
        )
    if memories:
        lines = [f"- ({item.get('category') or item.get('type')}) {item['content'][:400]}"
                 for item in memories]
        parts.append("Relevant workspace memory (may be outdated; verify before relying on it):\n"
                     + "\n".join(lines))
    return "\n\n".join(parts)
