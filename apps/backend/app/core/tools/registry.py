"""
JARV Backend - Tool Registry

Central registry for all JARV tools with discovery, instantiation, and metadata.
Tracks 100+ tools across 9 categories for agent use.
"""
from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass
import logging

from app.core.tools.base import ToolBase, ToolConfig
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


@dataclass
class ToolMetadata:
    """Metadata about a registered tool"""
    name: str
    tool_class: Type[ToolBase]
    description: str
    required_authority_level: int
    requires_approval: bool
    category: str
    is_implemented: bool = True


class ToolRegistry:
    """
    Central registry for all JARV tools.

    The registry:
    - Discovers and registers all available tools
    - Provides tool instantiation by name
    - Lists all registered tools with metadata
    - Validates tool implementation completeness
    - Categorizes tools by function (file, command, git, workspace, etc.)
    """

    # All required tools organized by category (100+ tools total)
    REQUIRED_TOOLS = {
        # File tools (15)
        "file_read": "Read file contents",
        "file_write": "Write content to file",
        "file_append": "Append content to file",
        "file_delete": "Delete file",
        "file_move": "Move or rename file",
        "file_copy": "Copy file",
        "file_search": "Search for files by pattern",
        "file_grep": "Search file contents with regex",
        "file_list": "List files in directory",
        "file_tree": "Show directory tree structure",
        "file_metadata": "Get file metadata (size, modified, etc.)",
        "file_permissions": "Get or set file permissions",
        "file_watch": "Watch file for changes",
        "file_diff": "Compare two files",
        "file_patch": "Apply patch to file",

        # Command tools (12)
        "command_run": "Run shell command",
        "command_background": "Run command in background",
        "command_pipe": "Pipe commands together",
        "command_sudo": "Run command with elevated privileges",
        "command_timeout": "Run command with timeout",
        "command_env": "Run command with environment variables",
        "terminal_open": "Open terminal session",
        "terminal_send": "Send input to terminal",
        "terminal_read": "Read terminal output",
        "terminal_close": "Close terminal session",
        "process_list": "List running processes",
        "process_kill": "Kill process by PID or name",

        # Git tools (20)
        "git_init": "Initialize git repository",
        "git_clone": "Clone git repository",
        "git_status": "Get git status",
        "git_add": "Stage files for commit",
        "git_commit": "Create git commit",
        "git_push": "Push commits to remote",
        "git_pull": "Pull changes from remote",
        "git_fetch": "Fetch from remote",
        "git_branch": "List, create, or delete branches",
        "git_checkout": "Checkout branch or commit",
        "git_merge": "Merge branches",
        "git_rebase": "Rebase branch",
        "git_diff": "Show git diff",
        "git_log": "Show git commit history",
        "git_blame": "Show line-by-line authorship",
        "git_tag": "Create or list tags",
        "git_stash": "Stash working changes",
        "git_reset": "Reset to specific commit",
        "git_revert": "Revert commit",
        "git_config": "Get or set git configuration",

        # Workspace tools (10)
        "workspace_create": "Create new workspace",
        "workspace_delete": "Delete workspace",
        "workspace_list": "List all workspaces",
        "workspace_switch": "Switch to workspace",
        "workspace_info": "Get workspace information",
        "workspace_update": "Update workspace settings",
        "workspace_backup": "Backup workspace",
        "workspace_restore": "Restore workspace from backup",
        "workspace_export": "Export workspace data",
        "workspace_import": "Import workspace data",

        # Company operation tools (15)
        "email_send": "Send email",
        "email_read": "Read emails",
        "email_search": "Search emails",
        "calendar_create_event": "Create calendar event",
        "calendar_list_events": "List calendar events",
        "calendar_update_event": "Update calendar event",
        "calendar_delete_event": "Delete calendar event",
        "crm_create_contact": "Create CRM contact",
        "crm_update_contact": "Update CRM contact",
        "crm_search_contacts": "Search CRM contacts",
        "crm_create_deal": "Create CRM deal",
        "crm_update_deal": "Update CRM deal",
        "slack_send": "Send Slack message",
        "slack_read": "Read Slack messages",
        "slack_search": "Search Slack history",

        # Memory tools (10)
        "memory_store": "Store information in agent memory",
        "memory_retrieve": "Retrieve information from memory",
        "memory_search": "Search agent memory",
        "memory_update": "Update memory entry",
        "memory_delete": "Delete memory entry",
        "memory_list": "List all memories",
        "memory_tag": "Tag memory for organization",
        "memory_export": "Export memories",
        "memory_import": "Import memories",
        "memory_stats": "Get memory usage statistics",

        # Experience tools (12)
        "experience_log_success": "Log successful action pattern",
        "experience_log_failure": "Log failed action pattern",
        "experience_query_pattern": "Query learned patterns",
        "experience_get_suggestions": "Get suggestions based on experience",
        "experience_rate_action": "Rate action quality",
        "experience_compare_approaches": "Compare different approaches",
        "experience_export": "Export learned experiences",
        "experience_import": "Import experiences",
        "experience_analyze": "Analyze experience patterns",
        "experience_visualize": "Visualize experience data",
        "experience_prune": "Remove outdated experiences",
        "experience_consolidate": "Consolidate similar experiences",

        # API tools (10)
        "http_get": "HTTP GET request",
        "http_post": "HTTP POST request",
        "http_put": "HTTP PUT request",
        "http_delete": "HTTP DELETE request",
        "http_patch": "HTTP PATCH request",
        "http_head": "HTTP HEAD request",
        "webhook_register": "Register webhook endpoint",
        "webhook_unregister": "Unregister webhook",
        "webhook_list": "List registered webhooks",
        "api_key_manage": "Manage API keys",

        # Analysis tools (12)
        "analyze_code": "Analyze code quality and complexity",
        "analyze_dependencies": "Analyze project dependencies",
        "analyze_security": "Security vulnerability scanning",
        "analyze_performance": "Performance profiling",
        "analyze_coverage": "Code coverage analysis",
        "analyze_metrics": "Calculate code metrics",
        "analyze_complexity": "Calculate cyclomatic complexity",
        "analyze_duplication": "Detect code duplication",
        "analyze_style": "Check code style compliance",
        "analyze_types": "Type checking and inference",
        "analyze_imports": "Analyze import structure",
        "analyze_architecture": "Architectural analysis",
    }

    # Tool categories
    CATEGORIES = {
        "file": [
            "file_read", "file_write", "file_append", "file_delete", "file_move",
            "file_copy", "file_search", "file_grep", "file_list", "file_tree",
            "file_metadata", "file_permissions", "file_watch", "file_diff", "file_patch"
        ],
        "command": [
            "command_run", "command_background", "command_pipe", "command_sudo",
            "command_timeout", "command_env", "terminal_open", "terminal_send",
            "terminal_read", "terminal_close", "process_list", "process_kill"
        ],
        "git": [
            "git_init", "git_clone", "git_status", "git_add", "git_commit",
            "git_push", "git_pull", "git_fetch", "git_branch", "git_checkout",
            "git_merge", "git_rebase", "git_diff", "git_log", "git_blame",
            "git_tag", "git_stash", "git_reset", "git_revert", "git_config"
        ],
        "workspace": [
            "workspace_create", "workspace_delete", "workspace_list", "workspace_switch",
            "workspace_info", "workspace_update", "workspace_backup", "workspace_restore",
            "workspace_export", "workspace_import"
        ],
        "company": [
            "email_send", "email_read", "email_search", "calendar_create_event",
            "calendar_list_events", "calendar_update_event", "calendar_delete_event",
            "crm_create_contact", "crm_update_contact", "crm_search_contacts",
            "crm_create_deal", "crm_update_deal", "slack_send", "slack_read", "slack_search"
        ],
        "memory": [
            "memory_store", "memory_retrieve", "memory_search", "memory_update",
            "memory_delete", "memory_list", "memory_tag", "memory_export",
            "memory_import", "memory_stats"
        ],
        "experience": [
            "experience_log_success", "experience_log_failure", "experience_query_pattern",
            "experience_get_suggestions", "experience_rate_action", "experience_compare_approaches",
            "experience_export", "experience_import", "experience_analyze", "experience_visualize",
            "experience_prune", "experience_consolidate"
        ],
        "api": [
            "http_get", "http_post", "http_put", "http_delete", "http_patch",
            "http_head", "webhook_register", "webhook_unregister", "webhook_list",
            "api_key_manage"
        ],
        "analysis": [
            "analyze_code", "analyze_dependencies", "analyze_security", "analyze_performance",
            "analyze_coverage", "analyze_metrics", "analyze_complexity", "analyze_duplication",
            "analyze_style", "analyze_types", "analyze_imports", "analyze_architecture"
        ],
    }

    def __init__(self):
        """Initialize tool registry"""
        self._tools: Dict[str, ToolMetadata] = {}
        self._initialized = False
        logger.info("Tool registry created")

    def register(
        self,
        tool_class: Type[ToolBase],
        category: str,
        description: Optional[str] = None,
    ) -> None:
        """
        Register a tool class.

        Args:
            tool_class: Tool class to register (must inherit from ToolBase)
            category: Tool category (file, command, git, etc.)
            description: Optional detailed description

        Raises:
            ValueError: If tool class is invalid or already registered
        """
        # Validate tool class
        if not issubclass(tool_class, ToolBase):
            raise ValueError(f"Tool class {tool_class} must inherit from ToolBase")

        # Create temporary instance to get metadata
        temp_config = ToolConfig()
        temp_instance = tool_class(temp_config)

        tool_name = temp_instance.name

        # Check if already registered
        if tool_name in self._tools:
            logger.warning(f"Tool {tool_name} is already registered, overwriting")

        # Register tool
        metadata = ToolMetadata(
            name=tool_name,
            tool_class=tool_class,
            description=description or temp_instance.description,
            required_authority_level=temp_instance.required_authority_level.value,
            requires_approval=temp_instance.requires_approval,
            category=category,
            is_implemented=True,
        )

        self._tools[tool_name] = metadata
        logger.info(
            f"Registered tool: {tool_name}",
            extra={
                "category": category,
                "authority_level": metadata.required_authority_level,
                "requires_approval": metadata.requires_approval,
            }
        )

    def register_placeholder(
        self,
        tool_name: str,
        category: str,
        description: str,
    ) -> None:
        """
        Register a placeholder for an unimplemented tool.

        This is used to track which tools still need to be implemented.

        Args:
            tool_name: Tool name
            category: Tool category
            description: Tool description
        """
        metadata = ToolMetadata(
            name=tool_name,
            tool_class=None,  # type: ignore
            description=description,
            required_authority_level=1,
            requires_approval=False,
            category=category,
            is_implemented=False,
        )

        self._tools[tool_name] = metadata
        logger.debug(f"Registered placeholder for tool: {tool_name}")

    def get(self, tool_name: str) -> Optional[Type[ToolBase]]:
        """
        Get tool class by name.

        Args:
            tool_name: Name of tool to retrieve

        Returns:
            Tool class or None if not found or not implemented
        """
        metadata = self._tools.get(tool_name)
        if not metadata:
            return None
        if not metadata.is_implemented:
            return None
        return metadata.tool_class

    def create(
        self,
        tool_name: str,
        config: ToolConfig,
    ) -> Optional[ToolBase]:
        """
        Create a tool instance by name.

        Args:
            tool_name: Name of tool to create
            config: Tool configuration

        Returns:
            Tool instance or None if not found

        Raises:
            ValueError: If tool is not implemented
        """
        metadata = self._tools.get(tool_name)
        if not metadata:
            logger.error(f"Tool {tool_name} not found in registry")
            return None

        if not metadata.is_implemented:
            raise ValueError(
                f"Tool {tool_name} is registered but not yet implemented. "
                f"Please implement this tool before using it."
            )

        # Create instance
        tool = metadata.tool_class(config)
        logger.info(
            f"Created tool instance: {tool_name}",
            extra={
                "tool_id": str(config.tool_id),
                "authority_level": config.authority_level.value,
            }
        )
        return tool

    def list_all(self) -> List[ToolMetadata]:
        """
        Get list of all registered tools.

        Returns:
            List of tool metadata
        """
        return list(self._tools.values())

    def list_by_category(self, category: str) -> List[ToolMetadata]:
        """
        Get tools in a specific category.

        Args:
            category: Category name

        Returns:
            List of tool metadata in category
        """
        return [
            metadata
            for metadata in self._tools.values()
            if metadata.category == category
        ]

    def list_implemented(self) -> List[ToolMetadata]:
        """
        Get list of implemented tools.

        Returns:
            List of implemented tool metadata
        """
        return [
            metadata
            for metadata in self._tools.values()
            if metadata.is_implemented
        ]

    def list_unimplemented(self) -> List[ToolMetadata]:
        """
        Get list of unimplemented tools.

        Returns:
            List of unimplemented tool metadata
        """
        return [
            metadata
            for metadata in self._tools.values()
            if not metadata.is_implemented
        ]

    def list_by_authority(self, max_authority: AuthorityLevel) -> List[ToolMetadata]:
        """
        Get tools available at specified authority level.

        Args:
            max_authority: Maximum authority level

        Returns:
            List of tool metadata available at this authority level
        """
        return [
            metadata
            for metadata in self._tools.values()
            if metadata.is_implemented and metadata.required_authority_level <= max_authority.value
        ]

    def get_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        """
        Get metadata for a tool.

        Args:
            tool_name: Tool name

        Returns:
            Tool metadata or None if not found
        """
        return self._tools.get(tool_name)

    def is_registered(self, tool_name: str) -> bool:
        """
        Check if a tool is registered.

        Args:
            tool_name: Tool name

        Returns:
            True if registered, False otherwise
        """
        return tool_name in self._tools

    def is_implemented(self, tool_name: str) -> bool:
        """
        Check if a tool is implemented.

        Args:
            tool_name: Tool name

        Returns:
            True if implemented, False otherwise
        """
        metadata = self._tools.get(tool_name)
        return metadata.is_implemented if metadata else False

    def get_categories(self) -> List[str]:
        """
        Get list of all categories.

        Returns:
            List of category names
        """
        return list(self.CATEGORIES.keys())

    def get_stats(self) -> Dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry stats
        """
        total = len(self.REQUIRED_TOOLS)
        implemented = len(self.list_implemented())
        unimplemented = len(self.list_unimplemented())

        by_category = {}
        for category in self.CATEGORIES.keys():
            tools_in_cat = self.list_by_category(category)
            by_category[category] = {
                "total": len(tools_in_cat),
                "implemented": len([t for t in tools_in_cat if t.is_implemented]),
                "unimplemented": len([t for t in tools_in_cat if not t.is_implemented]),
            }

        return {
            "total_required": total,
            "total_registered": len(self._tools),
            "implemented": implemented,
            "unimplemented": unimplemented,
            "completion_percentage": (implemented / total * 100) if total > 0 else 0,
            "by_category": by_category,
        }

    def validate_completeness(self) -> Dict[str, Any]:
        """
        Validate that all required tools are implemented.

        Returns:
            Dictionary with validation results
        """
        missing = []
        placeholders = []

        for tool_name, description in self.REQUIRED_TOOLS.items():
            if not self.is_registered(tool_name):
                missing.append({"name": tool_name, "description": description})
            elif not self.is_implemented(tool_name):
                placeholders.append({"name": tool_name, "description": description})

        is_complete = len(missing) == 0 and len(placeholders) == 0

        return {
            "is_complete": is_complete,
            "total_required": len(self.REQUIRED_TOOLS),
            "total_registered": len(self._tools),
            "total_implemented": len(self.list_implemented()),
            "missing_tools": missing,
            "placeholder_tools": placeholders,
        }

    def initialize_placeholders(self) -> None:
        """
        Register placeholders for all unimplemented required tools.

        This ensures the registry knows about all 100+ tools even if
        they're not yet implemented.
        """
        if self._initialized:
            return

        for tool_name, description in self.REQUIRED_TOOLS.items():
            if not self.is_registered(tool_name):
                # Find category for this tool
                category = "general"  # default
                for cat, tools in self.CATEGORIES.items():
                    if tool_name in tools:
                        category = cat
                        break

                self.register_placeholder(tool_name, category, description)

        self._initialized = True
        logger.info(
            f"Initialized tool registry with {len(self._tools)} tools",
            extra=self.get_stats()
        )


# Global registry instance
_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """
    Get the global tool registry instance.

    Returns:
        ToolRegistry singleton
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _registry.initialize_placeholders()

        # Import and register any implemented tools
        _register_implemented_tools(_registry)

    return _registry


def _register_implemented_tools(registry: ToolRegistry) -> None:
    """
    Register all implemented tools.

    This function imports and registers tools that have been implemented.
    As tools are implemented in Phase 5-7, they should be imported and
    registered here.

    Args:
        registry: Registry to register tools in
    """
    # File tools (15 tools - Phase 5.3)
    try:
        from app.tools.file import (
            FileReadTool,
            FileWriteTool,
            FileAppendTool,
            FileDeleteTool,
            FileMoveTool,
            FileCopyTool,
            FileSearchTool,
            FileGrepTool,
            FileListTool,
            FileTreeTool,
            FileMetadataTool,
            FilePermissionsTool,
            FileWatchTool,
            FileDiffTool,
            FilePatchTool,
        )

        # Register all file tools
        registry.register(FileReadTool, category="file")
        registry.register(FileWriteTool, category="file")
        registry.register(FileAppendTool, category="file")
        registry.register(FileDeleteTool, category="file")
        registry.register(FileMoveTool, category="file")
        registry.register(FileCopyTool, category="file")
        registry.register(FileSearchTool, category="file")
        registry.register(FileGrepTool, category="file")
        registry.register(FileListTool, category="file")
        registry.register(FileTreeTool, category="file")
        registry.register(FileMetadataTool, category="file")
        registry.register(FilePermissionsTool, category="file")
        registry.register(FileWatchTool, category="file")
        registry.register(FileDiffTool, category="file")
        registry.register(FilePatchTool, category="file")

        logger.info("Registered 15 file tools")

    except ImportError as e:
        logger.warning(f"File tools not available for registration: {e}")

    # Command tools (12 tools - Phase 5.4)
    try:
        from app.tools.command import (
            CommandRunTool,
            CommandBackgroundTool,
            CommandPipeTool,
            CommandSudoTool,
            CommandTimeoutTool,
            CommandEnvTool,
            TerminalOpenTool,
            TerminalSendTool,
            TerminalReadTool,
            TerminalCloseTool,
            ProcessListTool,
            ProcessKillTool,
        )

        # Register all command tools
        registry.register(CommandRunTool, category="command")
        registry.register(CommandBackgroundTool, category="command")
        registry.register(CommandPipeTool, category="command")
        registry.register(CommandSudoTool, category="command")
        registry.register(CommandTimeoutTool, category="command")
        registry.register(CommandEnvTool, category="command")
        registry.register(TerminalOpenTool, category="command")
        registry.register(TerminalSendTool, category="command")
        registry.register(TerminalReadTool, category="command")
        registry.register(TerminalCloseTool, category="command")
        registry.register(ProcessListTool, category="command")
        registry.register(ProcessKillTool, category="command")

        logger.info("Registered 12 command tools")

    except ImportError as e:
        logger.warning(f"Command tools not available for registration: {e}")

    # Git tools (20 tools - Phase 5.5)
    try:
        from app.tools.git import (
            GitInitTool, GitCloneTool, GitStatusTool, GitAddTool, GitCommitTool,
            GitPushTool, GitPullTool, GitFetchTool,
            GitBranchTool, GitCheckoutTool, GitMergeTool, GitRebaseTool,
            GitDiffTool, GitLogTool, GitBlameTool,
            GitTagTool, GitStashTool, GitResetTool, GitRevertTool, GitConfigTool,
        )

        # Register all git tools
        for tool in [GitInitTool, GitCloneTool, GitStatusTool, GitAddTool, GitCommitTool,
                     GitPushTool, GitPullTool, GitFetchTool,
                     GitBranchTool, GitCheckoutTool, GitMergeTool, GitRebaseTool,
                     GitDiffTool, GitLogTool, GitBlameTool,
                     GitTagTool, GitStashTool, GitResetTool, GitRevertTool, GitConfigTool]:
            registry.register(tool, category="git")

        logger.info("Registered 20 git tools")

    except ImportError as e:
        logger.warning(f"Git tools not available for registration: {e}")

    # Workspace tools (10 tools - Phase 5.6)
    try:
        from app.tools.workspace import (
            WorkspaceCreateTool, WorkspaceDeleteTool, WorkspaceListTool,
            WorkspaceSwitchTool, WorkspaceInfoTool, WorkspaceUpdateTool,
            WorkspaceBackupTool, WorkspaceRestoreTool,
            WorkspaceExportTool, WorkspaceImportTool,
        )

        for tool in [WorkspaceCreateTool, WorkspaceDeleteTool, WorkspaceListTool,
                     WorkspaceSwitchTool, WorkspaceInfoTool, WorkspaceUpdateTool,
                     WorkspaceBackupTool, WorkspaceRestoreTool,
                     WorkspaceExportTool, WorkspaceImportTool]:
            registry.register(tool, category="workspace")

        logger.info("Registered 10 workspace tools")

    except ImportError as e:
        logger.warning(f"Workspace tools not available for registration: {e}")

    # Company tools (15 tools - Phase 5.7)
    try:
        from app.tools.company import (
            EmailSendTool, EmailReadTool, EmailSearchTool,
            CalendarCreateEventTool, CalendarListEventsTool, CalendarUpdateEventTool, CalendarDeleteEventTool,
            CrmCreateContactTool, CrmUpdateContactTool, CrmSearchContactsTool,
            CrmCreateDealTool, CrmUpdateDealTool,
            SlackSendTool, SlackReadTool, SlackSearchTool,
        )

        # Register all company tools
        for tool in [
            EmailSendTool, EmailReadTool, EmailSearchTool,
            CalendarCreateEventTool, CalendarListEventsTool, CalendarUpdateEventTool, CalendarDeleteEventTool,
            CrmCreateContactTool, CrmUpdateContactTool, CrmSearchContactsTool,
            CrmCreateDealTool, CrmUpdateDealTool,
            SlackSendTool, SlackReadTool, SlackSearchTool,
        ]:
            registry.register(tool, category="company")

        logger.info("Registered 15 company tools")

    except ImportError as e:
        logger.warning(f"Company tools not available for registration: {e}")

    # Memory tools (10 tools - Phase 5.8)
    try:
        from app.tools.memory import (
            MemoryStoreTool,
            MemoryRetrieveTool,
            MemorySearchTool,
            MemoryUpdateTool,
            MemoryDeleteTool,
            MemoryListTool,
            MemoryTagTool,
            MemoryExportTool,
            MemoryImportTool,
            MemoryStatsTool,
        )

        # Register all memory tools
        for tool in [
            MemoryStoreTool,
            MemoryRetrieveTool,
            MemorySearchTool,
            MemoryUpdateTool,
            MemoryDeleteTool,
            MemoryListTool,
            MemoryTagTool,
            MemoryExportTool,
            MemoryImportTool,
            MemoryStatsTool,
        ]:
            registry.register(tool, category="memory")

        logger.info("Registered 10 memory tools")

    except ImportError as e:
        logger.warning(f"Memory tools not available for registration: {e}")

    # Experience tools (12 tools - Phase 5.9)
    try:
        from app.tools.experience import (
            ExperienceLogSuccessTool,
            ExperienceLogFailureTool,
            ExperienceRateActionTool,
            ExperienceQueryPatternTool,
            ExperienceGetSuggestionsTool,
            ExperienceCompareApproachesTool,
            ExperienceExportTool,
            ExperienceImportTool,
            ExperienceAnalyzeTool,
            ExperienceVisualizeTool,
            ExperiencePruneTool,
            ExperienceConsolidateTool,
        )

        # Register all experience tools
        for tool in [
            ExperienceLogSuccessTool,
            ExperienceLogFailureTool,
            ExperienceRateActionTool,
            ExperienceQueryPatternTool,
            ExperienceGetSuggestionsTool,
            ExperienceCompareApproachesTool,
            ExperienceExportTool,
            ExperienceImportTool,
            ExperienceAnalyzeTool,
            ExperienceVisualizeTool,
            ExperiencePruneTool,
            ExperienceConsolidateTool,
        ]:
            registry.register(tool, category="experience")

        logger.info("Registered 12 experience tools")

    except ImportError as e:
        logger.warning(f"Experience tools not available for registration: {e}")

    # API tools (10 tools - Phase 5.10)
    try:
        from app.tools.api import (
            HttpGetTool,
            HttpPostTool,
            HttpPutTool,
            HttpDeleteTool,
            HttpPatchTool,
            HttpHeadTool,
            WebhookRegisterTool,
            WebhookUnregisterTool,
            WebhookListTool,
            ApiKeyManageTool,
        )

        # Register all API tools
        for tool in [
            HttpGetTool,
            HttpPostTool,
            HttpPutTool,
            HttpDeleteTool,
            HttpPatchTool,
            HttpHeadTool,
            WebhookRegisterTool,
            WebhookUnregisterTool,
            WebhookListTool,
            ApiKeyManageTool,
        ]:
            registry.register(tool, category="api")

        logger.info("Registered 10 API tools")

    except ImportError as e:
        logger.warning(f"API tools not available for registration: {e}")

    # Analysis tools (12 tools - Phase 5.11)
    try:
        from app.tools.analysis import (
            AnalyzeCodeTool,
            AnalyzeComplexityTool,
            AnalyzeDuplicationTool,
            AnalyzeMetricsTool,
            AnalyzeStyleTool,
            AnalyzeTypesTool,
            AnalyzeCoverageTool,
            AnalyzeSecurityTool,
            AnalyzeDependenciesTool,
            AnalyzeImportsTool,
            AnalyzeArchitectureTool,
            AnalyzePerformanceTool,
        )

        # Register all analysis tools
        for tool in [
            AnalyzeCodeTool,
            AnalyzeComplexityTool,
            AnalyzeDuplicationTool,
            AnalyzeMetricsTool,
            AnalyzeStyleTool,
            AnalyzeTypesTool,
            AnalyzeCoverageTool,
            AnalyzeSecurityTool,
            AnalyzeDependenciesTool,
            AnalyzeImportsTool,
            AnalyzeArchitectureTool,
            AnalyzePerformanceTool,
        ]:
            registry.register(tool, category="analysis")

        logger.info("Registered 12 analysis tools")

    except ImportError as e:
        logger.warning(f"Analysis tools not available for registration: {e}")


def register_tool(
    tool_class: Type[ToolBase],
    category: str,
    description: Optional[str] = None,
) -> None:
    """
    Convenience function to register a tool with the global registry.

    Args:
        tool_class: Tool class to register
        category: Tool category
        description: Optional description
    """
    registry = get_registry()
    registry.register(tool_class, category, description)


def create_tool(tool_name: str, config: ToolConfig) -> Optional[ToolBase]:
    """
    Convenience function to create a tool from the global registry.

    Args:
        tool_name: Name of tool to create
        config: Tool configuration

    Returns:
        Tool instance or None if not found
    """
    registry = get_registry()
    return registry.create(tool_name, config)


def list_tools(
    category: Optional[str] = None,
    only_implemented: bool = False,
    max_authority: Optional[AuthorityLevel] = None,
) -> List[ToolMetadata]:
    """
    Convenience function to list tools from the global registry.

    Args:
        category: Optional category filter
        only_implemented: Only return implemented tools
        max_authority: Only return tools available at this authority level

    Returns:
        List of tool metadata
    """
    registry = get_registry()

    if category:
        tools = registry.list_by_category(category)
    elif max_authority is not None:
        tools = registry.list_by_authority(max_authority)
    else:
        tools = registry.list_all()

    if only_implemented:
        tools = [t for t in tools if t.is_implemented]

    return tools
