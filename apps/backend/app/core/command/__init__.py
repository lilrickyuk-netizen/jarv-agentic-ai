"""
JARV Backend - Command Execution Package

Provides the live command pipeline that turns a dashboard text/voice command
into: real Claude planning -> agent selection -> task lifecycle -> execution ->
result, with safety/approval gates for actions that modify files, deploy, or
spend money.
"""
from app.core.command.service import CommandService, classify_command_safety

__all__ = ["CommandService", "classify_command_safety"]
