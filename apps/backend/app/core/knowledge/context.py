"""Context-local specialist knowledge for real provider prompts."""
from contextvars import ContextVar, Token
from typing import Any, Dict, List, Optional


_knowledge_context: ContextVar[List[Dict[str, Any]]] = ContextVar(
    "jarv_specialist_knowledge", default=[]
)


def set_knowledge_context(
    records: List[Dict[str, Any]], *, reset_token: Optional[Token] = None,
):
    """Set task-scoped provider context or restore the previous value."""
    if reset_token is not None:
        _knowledge_context.reset(reset_token)
        return None
    return _knowledge_context.set(records)


def get_knowledge_context() -> List[Dict[str, Any]]:
    """Read the current task's specialist knowledge records."""
    return _knowledge_context.get()