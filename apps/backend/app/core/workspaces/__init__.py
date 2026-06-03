"""
JARV Backend - Workspace System

Dynamic workspace management with rules, templates, and lifecycle management.
"""
from app.core.workspaces.manager import WorkspaceManager, create_workspace, get_workspace
from app.core.workspaces.rules import RulesEngine, evaluate_rule
from app.core.workspaces.templates import TemplateManager, create_from_template
from app.core.workspaces.scanner import WorkspaceScanner, scan_workspace

__all__ = [
    "WorkspaceManager",
    "create_workspace",
    "get_workspace",
    "RulesEngine",
    "evaluate_rule",
    "TemplateManager",
    "create_from_template",
    "WorkspaceScanner",
    "scan_workspace",
]
