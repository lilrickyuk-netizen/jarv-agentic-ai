"""
JARV Backend - Self-Healing Monitoring Service

Monitors system health, logs, and errors to detect issues requiring self-healing.
"""
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import logging
import httpx
from collections import deque

logger = logging.getLogger(__name__)


class MonitorStatus(str, Enum):
    """Status of a monitor"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class IssueDetection:
    """Represents a detected issue"""

    def __init__(
        self,
        issue_type: str,
        severity: str,
        description: str,
        affected_systems: List[str],
        detection_time: datetime,
        metrics: Dict[str, Any],
    ):
        self.issue_type = issue_type
        self.severity = severity
        self.description = description
        self.affected_systems = affected_systems
        self.detection_time = detection_time
        self.metrics = metrics

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "affected_systems": self.affected_systems,
            "detection_time": self.detection_time.isoformat(),
            "metrics": self.metrics,
        }


class MonitorBase:
    """Base class for all monitors"""

    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self.status = MonitorStatus.UNKNOWN
        self.last_check: Optional[datetime] = None
        self.last_issue: Optional[IssueDetection] = None
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def check(self) -> Optional[IssueDetection]:
        """Perform health check - to be implemented by subclasses"""
        raise NotImplementedError

    async def start(self):
        """Start monitoring"""
        if self.is_running:
            logger.warning(f"{self.__class__.__name__} is already running")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"{self.__class__.__name__} started")

    async def stop(self):
        """Stop monitoring"""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"{self.__class__.__name__} stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.is_running:
            try:
                issue = await self.check()
                self.last_check = datetime.utcnow()

                if issue:
                    self.last_issue = issue
                    self.status = MonitorStatus.UNHEALTHY
                    logger.warning(
                        f"{self.__class__.__name__} detected issue: {issue.description}"
                    )
                else:
                    self.status = MonitorStatus.HEALTHY

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Error in {self.__class__.__name__} monitor loop: {e}")
                self.status = MonitorStatus.UNKNOWN
                await asyncio.sleep(self.check_interval)


class HealthCheckMonitor(MonitorBase):
    """Monitor for health checks of websites, APIs, and services"""

    def __init__(
        self,
        targets: List[Dict[str, str]],
        check_interval: int = 60,
        timeout: int = 10,
    ):
        super().__init__(check_interval)
        self.targets = targets  # [{"name": "API", "url": "https://...", "type": "http"}]
        self.timeout = timeout
        self.failure_counts: Dict[str, int] = {}

    async def check(self) -> Optional[IssueDetection]:
        """Check health of all targets"""
        failed_targets = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for target in self.targets:
                try:
                    if target["type"] == "http":
                        response = await client.get(target["url"])
                        if response.status_code >= 500:
                            failed_targets.append(target["name"])
                            self.failure_counts[target["name"]] = (
                                self.failure_counts.get(target["name"], 0) + 1
                            )
                        else:
                            self.failure_counts[target["name"]] = 0

                except Exception as e:
                    logger.error(f"Health check failed for {target['name']}: {e}")
                    failed_targets.append(target["name"])
                    self.failure_counts[target["name"]] = (
                        self.failure_counts.get(target["name"], 0) + 1
                    )

        # Detect issues based on consecutive failures
        critical_failures = [
            name for name in failed_targets
            if self.failure_counts.get(name, 0) >= 3
        ]

        if critical_failures:
            return IssueDetection(
                issue_type="website_down" if "website" in critical_failures[0].lower() else "service_down",
                severity="critical",
                description=f"Services down: {', '.join(critical_failures)}",
                affected_systems=critical_failures,
                detection_time=datetime.utcnow(),
                metrics={
                    "failed_targets": critical_failures,
                    "failure_counts": {k: v for k, v in self.failure_counts.items() if k in critical_failures},
                },
            )

        return None


class LogMonitor(MonitorBase):
    """Monitor system logs for anomalies"""

    def __init__(
        self,
        log_sources: List[str],
        check_interval: int = 30,
        anomaly_threshold: int = 100,
    ):
        super().__init__(check_interval)
        self.log_sources = log_sources
        self.anomaly_threshold = anomaly_threshold
        self.recent_logs: deque = deque(maxlen=1000)
        self.pattern_counts: Dict[str, int] = {}

    async def check(self) -> Optional[IssueDetection]:
        """Check logs for anomalies"""
        # In a real implementation, this would connect to log aggregation services
        # like CloudWatch, Datadog, or read from log files

        # Simulate log analysis
        error_patterns = self._analyze_log_patterns()

        if error_patterns:
            most_common = max(error_patterns.items(), key=lambda x: x[1])
            if most_common[1] > self.anomaly_threshold:
                return IssueDetection(
                    issue_type="log_anomaly",
                    severity="high",
                    description=f"High frequency of log pattern: {most_common[0]}",
                    affected_systems=self.log_sources,
                    detection_time=datetime.utcnow(),
                    metrics={
                        "pattern": most_common[0],
                        "count": most_common[1],
                        "threshold": self.anomaly_threshold,
                    },
                )

        return None

    def _analyze_log_patterns(self) -> Dict[str, int]:
        """Analyze recent logs for patterns"""
        pattern_counts: Dict[str, int] = {}

        for log in self.recent_logs:
            entry = log.get("entry", "")

            if "ERROR" in entry:
                pattern_counts["error"] = pattern_counts.get("error", 0) + 1
            if "CRITICAL" in entry:
                pattern_counts["critical"] = pattern_counts.get("critical", 0) + 1
            if "timeout" in entry.lower():
                pattern_counts["timeout"] = pattern_counts.get("timeout", 0) + 1
            if "connection" in entry.lower():
                pattern_counts["connection"] = pattern_counts.get("connection", 0) + 1

        return pattern_counts

    def add_log_entry(self, log_entry: str):
        """Add a log entry for monitoring"""
        self.recent_logs.append({
            "timestamp": datetime.utcnow(),
            "entry": log_entry,
        })


class ErrorMonitor(MonitorBase):
    """Monitor error rates and spikes"""

    def __init__(
        self,
        error_sources: List[Dict[str, str]],
        check_interval: int = 60,
        spike_threshold: float = 2.0,  # 2x normal rate
        baseline_window: int = 300,  # 5 minutes
    ):
        super().__init__(check_interval)
        self.error_sources = error_sources  # [{"name": "API", "type": "api_errors"}]
        self.spike_threshold = spike_threshold
        self.baseline_window = baseline_window
        self.error_history: Dict[str, deque] = {
            source["name"]: deque(maxlen=100)
            for source in error_sources
        }

    async def check(self) -> Optional[IssueDetection]:
        """Check for error spikes"""
        spikes = []

        for source in self.error_sources:
            source_name = source["name"]
            history = self.error_history[source_name]

            if len(history) < 10:
                continue  # Not enough data

            # Calculate baseline error rate
            recent_errors = list(history)[-10:]
            baseline_rate = sum(recent_errors) / len(recent_errors)

            # Get current error rate
            current_rate = recent_errors[-1] if recent_errors else 0

            # Detect spike
            if baseline_rate > 0 and current_rate > baseline_rate * self.spike_threshold:
                spikes.append({
                    "source": source_name,
                    "baseline_rate": baseline_rate,
                    "current_rate": current_rate,
                    "spike_multiplier": current_rate / baseline_rate,
                })

        if spikes:
            worst_spike = max(spikes, key=lambda x: x["spike_multiplier"])
            return IssueDetection(
                issue_type="error_spike",
                severity="high",
                description=f"Error spike detected in {worst_spike['source']}",
                affected_systems=[s["source"] for s in spikes],
                detection_time=datetime.utcnow(),
                metrics={
                    "spikes": spikes,
                    "threshold": self.spike_threshold,
                },
            )

        return None

    def record_error(self, source_name: str, error_count: int):
        """Record error count for a source"""
        if source_name in self.error_history:
            self.error_history[source_name].append(error_count)


class MonitoringService:
    """Central monitoring service that coordinates all monitors"""

    def __init__(self):
        self.monitors: List[MonitorBase] = []
        self.issue_handlers: List[Callable[[IssueDetection], None]] = []
        self.is_running = False

    def add_monitor(self, monitor: MonitorBase):
        """Add a monitor to the service"""
        self.monitors.append(monitor)
        logger.info(f"Added monitor: {monitor.__class__.__name__}")

    def add_issue_handler(self, handler: Callable[[IssueDetection], None]):
        """Add a handler for detected issues"""
        self.issue_handlers.append(handler)

    async def start(self):
        """Start all monitors"""
        if self.is_running:
            logger.warning("MonitoringService is already running")
            return

        self.is_running = True

        # Start all monitors
        for monitor in self.monitors:
            await monitor.start()

        # Start issue detection loop
        asyncio.create_task(self._issue_detection_loop())

        logger.info("MonitoringService started")

    async def stop(self):
        """Stop all monitors"""
        self.is_running = False

        # Stop all monitors
        for monitor in self.monitors:
            await monitor.stop()

        logger.info("MonitoringService stopped")

    async def _issue_detection_loop(self):
        """Loop that checks monitors for detected issues"""
        while self.is_running:
            try:
                for monitor in self.monitors:
                    if monitor.last_issue:
                        # Issue detected, notify handlers
                        for handler in self.issue_handlers:
                            try:
                                if asyncio.iscoroutinefunction(handler):
                                    await handler(monitor.last_issue)
                                else:
                                    handler(monitor.last_issue)
                            except Exception as e:
                                logger.error(f"Error in issue handler: {e}")

                        # Clear the issue after handling
                        monitor.last_issue = None

                await asyncio.sleep(10)  # Check every 10 seconds

            except Exception as e:
                logger.error(f"Error in issue detection loop: {e}")
                await asyncio.sleep(10)

    def get_status(self) -> Dict[str, Any]:
        """Get status of all monitors"""
        return {
            "is_running": self.is_running,
            "monitors": [
                {
                    "name": monitor.__class__.__name__,
                    "status": monitor.status.value,
                    "last_check": monitor.last_check.isoformat() if monitor.last_check else None,
                }
                for monitor in self.monitors
            ],
        }
