"""
JARV Backend - Process Management Tools

Process management tools: list, kill.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import psutil
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== PROCESS LIST TOOL =====

class ProcessListInput(BaseModel):
    """Input schema for process list tool"""
    filter_name: Optional[str] = Field(None, description="Filter by process name (substring)")
    filter_user: Optional[str] = Field(None, description="Filter by username")
    sort_by: str = Field(default="pid", description="Sort by: pid, cpu, memory, name")
    limit: int = Field(default=50, ge=1, le=1000, description="Maximum processes to return")


class ProcessInfo(BaseModel):
    """Single process information"""
    pid: int = Field(..., description="Process ID")
    name: str = Field(..., description="Process name")
    username: str = Field(..., description="Username")
    status: str = Field(..., description="Process status")
    cpu_percent: float = Field(..., description="CPU usage percentage")
    memory_mb: float = Field(..., description="Memory usage in MB")
    cmdline: str = Field(..., description="Command line")


class ProcessListOutput(BaseModel):
    """Output schema for process list tool"""
    processes: List[ProcessInfo] = Field(..., description="List of processes")
    count: int = Field(..., description="Number of processes")
    total_processes: int = Field(..., description="Total processes on system")


class ProcessListTool(ToolBase):
    """Tool for listing running processes"""

    @property
    def name(self) -> str:
        return "process_list"

    @property
    def description(self) -> str:
        return "List running processes with details (PID, name, CPU, memory). Can filter and sort."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ProcessListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ProcessListOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """List processes"""
        filter_name = input_data.get("filter_name")
        filter_user = input_data.get("filter_user")
        sort_by = input_data["sort_by"]
        limit = input_data["limit"]

        try:
            # Get all processes
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'status', 'cpu_percent', 'memory_info', 'cmdline']):
                try:
                    # Get process info
                    pinfo = proc.info

                    # Apply filters
                    if filter_name and filter_name.lower() not in pinfo['name'].lower():
                        continue

                    if filter_user and filter_user != pinfo.get('username'):
                        continue

                    # Get memory in MB
                    memory_mb = pinfo['memory_info'].rss / (1024 * 1024) if pinfo.get('memory_info') else 0

                    # Get command line
                    cmdline = ' '.join(pinfo.get('cmdline', [])) if pinfo.get('cmdline') else pinfo['name']

                    processes.append({
                        'pid': pinfo['pid'],
                        'name': pinfo['name'],
                        'username': pinfo.get('username', 'unknown'),
                        'status': pinfo.get('status', 'unknown'),
                        'cpu_percent': pinfo.get('cpu_percent', 0.0),
                        'memory_mb': round(memory_mb, 2),
                        'cmdline': cmdline[:200],  # Truncate long command lines
                    })

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Skip processes we can't access
                    continue

            total_processes = len(processes)

            # Sort processes
            sort_keys = {
                'pid': lambda p: p['pid'],
                'cpu': lambda p: p['cpu_percent'],
                'memory': lambda p: p['memory_mb'],
                'name': lambda p: p['name'].lower(),
            }

            if sort_by in sort_keys:
                processes.sort(key=sort_keys[sort_by], reverse=(sort_by in ['cpu', 'memory']))

            # Limit results
            processes = processes[:limit]

            return self.create_result(
                success=True,
                result_data={
                    "processes": processes,
                    "count": len(processes),
                    "total_processes": total_processes,
                },
                output_text=f"Listed {len(processes)} of {total_processes} processes",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to list processes: {str(e)}",
            )


# ===== PROCESS KILL TOOL =====

class ProcessKillInput(BaseModel):
    """Input schema for process kill tool"""
    pid: Optional[int] = Field(None, description="Process ID to kill")
    name: Optional[str] = Field(None, description="Process name to kill (kills all matching)")
    signal: str = Field(default="TERM", description="Signal to send: TERM, KILL, INT, etc.")
    force: bool = Field(default=False, description="Force kill (SIGKILL) if TERM fails")


class ProcessKillOutput(BaseModel):
    """Output schema for process kill tool"""
    killed_pids: List[int] = Field(..., description="List of killed process IDs")
    count: int = Field(..., description="Number of processes killed")
    message: str = Field(..., description="Status message")


class ProcessKillTool(ToolBase):
    """Tool for killing processes"""

    @property
    def name(self) -> str:
        return "process_kill"

    @property
    def description(self) -> str:
        return "Kill process(es) by PID or name. Can send different signals. Requires approval."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ProcessKillInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ProcessKillOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    @property
    def requires_approval(self) -> bool:
        return True  # Killing processes is risky

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Kill process(es)"""
        pid = input_data.get("pid")
        name = input_data.get("name")
        signal_name = input_data["signal"]
        force = input_data["force"]

        try:
            # Validate input
            if not pid and not name:
                return self.create_result(
                    success=False,
                    error_message="Either pid or name must be provided",
                )

            # Parse signal
            import signal as sig_module
            signal_map = {
                "TERM": sig_module.SIGTERM,
                "KILL": sig_module.SIGKILL,
                "INT": sig_module.SIGINT,
                "HUP": sig_module.SIGHUP,
                "QUIT": sig_module.SIGQUIT,
            }

            if signal_name not in signal_map:
                return self.create_result(
                    success=False,
                    error_message=f"Unknown signal: {signal_name}. Use TERM, KILL, INT, HUP, or QUIT",
                )

            signal = signal_map[signal_name]

            # Find processes to kill
            processes_to_kill = []

            if pid:
                # Kill by PID
                try:
                    proc = psutil.Process(pid)
                    processes_to_kill.append(proc)
                except psutil.NoSuchProcess:
                    return self.create_result(
                        success=False,
                        error_message=f"Process with PID {pid} not found",
                    )

            elif name:
                # Kill by name
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if name.lower() in proc.info['name'].lower():
                            processes_to_kill.append(proc)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                if not processes_to_kill:
                    return self.create_result(
                        success=False,
                        error_message=f"No processes found with name '{name}'",
                    )

            # Kill processes
            killed_pids = []
            for proc in processes_to_kill:
                try:
                    # Send signal
                    proc.send_signal(signal)

                    # If force=True and signal wasn't KILL, wait and force kill if needed
                    if force and signal != sig_module.SIGKILL:
                        try:
                            proc.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            # Force kill
                            proc.kill()

                    killed_pids.append(proc.pid)

                except psutil.NoSuchProcess:
                    # Process already terminated
                    killed_pids.append(proc.pid)
                except psutil.AccessDenied:
                    logger.warning(f"Access denied when killing process {proc.pid}")
                    continue

            if not killed_pids:
                return self.create_result(
                    success=False,
                    error_message="Failed to kill any processes (access denied?)",
                )

            return self.create_result(
                success=True,
                result_data={
                    "killed_pids": killed_pids,
                    "count": len(killed_pids),
                    "message": f"Killed {len(killed_pids)} process(es)",
                },
                output_text=f"Killed {len(killed_pids)} process(es): {killed_pids}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to kill process(es): {str(e)}",
            )
