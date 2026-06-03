"""
JARV Backend - Self-Healing Workflows

Orchestrates detection, diagnosis, execution, rollback, and learning from incidents.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from uuid import UUID, uuid4
import asyncio
import logging
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.operations import Incident
from app.models.runbook import Runbook, RunbookVersion
from app.models.memory import Memory
from app.models.self_evolution import ExperienceRecord
from .monitoring import IssueDetection
from .runbooks import (
    RunbookBase,
    WebsiteDownRunbook,
    APIErrorSpikeRunbook,
    QueueStuckRunbook,
    PaymentWebhookRunbook,
    BugReportsIncreasingRunbook,
    ServerPressureRunbook,
    SSLDomainRunbook,
    RunbookStatus,
    RunbookResult,
    IntegrationRequiredError,
)

logger = logging.getLogger(__name__)

SELF_HEALING_SYSTEM_AGENT_ID = UUID('00000000-0000-0000-0000-000000000001')


class SelfHealingWorkflow:
    """
    Main self-healing workflow that coordinates:
    1. Detection - identify issues
    2. Diagnosis - determine root cause
    3. Runbook Selection - choose appropriate fix
    4. Execution - apply the fix
    5. Verification - confirm recovery
    6. Learning - create experience record
    """

    def __init__(self, workspace_id: Optional[UUID] = None):
        self.workspace_id = workspace_id
        self.runbooks: Dict[str, RunbookBase] = {
            "website_down": WebsiteDownRunbook(),
            "api_error_spike": APIErrorSpikeRunbook(),
            "queue_stuck": QueueStuckRunbook(),
            "payment_webhook_failure": PaymentWebhookRunbook(),
            "bug_reports_increasing": BugReportsIncreasingRunbook(),
            "server_pressure": ServerPressureRunbook(),
            "ssl_domain_issue": SSLDomainRunbook(),
        }

    async def execute(
        self,
        issue: IssueDetection,
        user_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Execute self-healing workflow for detected issue

        Workflow:
        1. Create incident record
        2. Select appropriate runbook
        3. Diagnose root cause
        4. Check if approval required
        5. Execute recovery (pause if approval needed)
        6. Verify recovery
        7. Update incident record
        8. Create memory
        9. Create experience record
        """
        incident_id = None
        runbook_result = None

        try:
            # Step 1: Create incident record
            incident_id = await self._create_incident(issue, user_id)
            logger.info(f"Created incident {incident_id} for {issue.issue_type}")

            # Step 2: Select appropriate runbook
            runbook = await self._select_runbook(issue)
            if not runbook:
                logger.warning(f"No runbook found for issue type: {issue.issue_type}")
                await self._update_incident_status(
                    incident_id,
                    "open",
                    "No automated runbook available",
                )
                return {
                    "success": False,
                    "incident_id": str(incident_id),
                    "error": "No runbook available",
                    "requires_manual_intervention": True,
                }

            logger.info(f"Selected runbook: {runbook.runbook_type}")

            # Step 3: Diagnose root cause
            await self._update_incident_status(incident_id, "investigating", None)
            diagnosis = await runbook.diagnose(issue.metrics)
            logger.info(f"Diagnosis: {diagnosis}")

            # Step 4: Check if approval required
            if runbook.requires_approval:
                logger.info(f"Runbook requires approval - authority level {runbook.authority_level}")
                await self._update_incident_status(
                    incident_id,
                    "awaiting_approval",
                    f"Runbook requires approval (authority level {runbook.authority_level})",
                )
                return {
                    "success": False,
                    "incident_id": str(incident_id),
                    "requires_approval": True,
                    "runbook_type": runbook.runbook_type,
                    "diagnosis": diagnosis,
                    "authority_level": runbook.authority_level,
                    "message": "Awaiting Richard's approval to proceed with recovery",
                }

            # Step 5: Execute recovery
            await self._update_incident_status(incident_id, "fixing", None)
            runbook_result = await runbook.execute(diagnosis)
            logger.info(f"Runbook execution result: {runbook_result.status}")

            # Step 6: Verify recovery
            if runbook_result.success:
                await self._update_incident_status(
                    incident_id,
                    "resolved",
                    f"Successfully recovered using {runbook.runbook_type} runbook",
                )

                # Step 7: Create memory of this incident
                await self._create_incident_memory(incident_id, issue, diagnosis, runbook_result)

                # Step 8: Create experience record for self-evolution
                await self._create_experience_record(
                    incident_id,
                    issue,
                    diagnosis,
                    runbook_result,
                    user_id,
                )

                logger.info(f"Self-healing completed successfully for incident {incident_id}")

                return {
                    "success": True,
                    "incident_id": str(incident_id),
                    "runbook_type": runbook.runbook_type,
                    "diagnosis": diagnosis,
                    "recovery_actions": runbook_result.recovery_actions,
                    "message": "Platform health restored automatically",
                }

            else:
                # Recovery failed - attempt rollback
                await self._update_incident_status(
                    incident_id,
                    "failed",
                    f"Recovery failed: {runbook_result.error_message}",
                )

                # Attempt rollback
                rollback_workflow = RollbackWorkflow(self.workspace_id)
                rollback_success = await rollback_workflow.execute(runbook, runbook_result)

                if rollback_success:
                    await self._update_incident_status(
                        incident_id,
                        "rolled_back",
                        "Recovery failed, successfully rolled back changes",
                    )

                return {
                    "success": False,
                    "incident_id": str(incident_id),
                    "runbook_type": runbook.runbook_type,
                    "diagnosis": diagnosis,
                    "error": runbook_result.error_message,
                    "rolled_back": rollback_success,
                    "requires_manual_intervention": True,
                }

        except Exception as e:
            logger.error(f"Error in self-healing workflow: {e}")
            if incident_id:
                await self._update_incident_status(
                    incident_id,
                    "failed",
                    f"Workflow error: {str(e)}",
                )
            return {
                "success": False,
                "incident_id": str(incident_id) if incident_id else None,
                "error": str(e),
                "requires_manual_intervention": True,
            }

    async def _create_incident(
        self,
        issue: IssueDetection,
        user_id: Optional[UUID],
    ) -> UUID:
        """Create incident record in database"""
        async with AsyncSessionLocal() as db:
            incident = Incident(
                workspace_id=self.workspace_id,
                incident_number=f"INC-{datetime.utcnow().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
                title=issue.description,
                description=f"Automatically detected: {issue.description}",
                severity=issue.severity,
                priority="high" if issue.severity == "critical" else "medium",
                category="performance",
                incident_type=issue.issue_type,
                status="open",
                affected_systems=issue.affected_systems,
                detected_at=issue.detection_time,
            )
            db.add(incident)
            await db.commit()
            await db.refresh(incident)
            return incident.id

    async def _select_runbook(self, issue: IssueDetection) -> Optional[RunbookBase]:
        """Select appropriate runbook based on issue type"""
        for runbook_type, runbook in self.runbooks.items():
            if await runbook.detect(issue.metrics):
                return runbook
        return None

    async def _update_incident_status(
        self,
        incident_id: UUID,
        status: str,
        resolution: Optional[str],
    ):
        """Update incident status in database"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Incident).where(Incident.id == incident_id)
            )
            incident = result.scalar_one_or_none()

            if incident:
                incident.status = status
                if resolution:
                    incident.resolution = resolution

                if status == "resolved":
                    incident.resolved_at = datetime.utcnow()

                await db.commit()

    async def _create_incident_memory(
        self,
        incident_id: UUID,
        issue: IssueDetection,
        diagnosis: Dict[str, Any],
        result: RunbookResult,
    ):
        """Create memory of this incident for future reference"""
        workflow = IncidentMemoryWorkflow(self.workspace_id)
        await workflow.execute(incident_id, issue, diagnosis, result)

    async def _create_experience_record(
        self,
        incident_id: UUID,
        issue: IssueDetection,
        diagnosis: Dict[str, Any],
        result: RunbookResult,
        user_id: Optional[UUID],
    ):
        """Create experience record for self-evolution"""
        workflow = ExperienceRecordWorkflow(self.workspace_id)
        await workflow.execute(incident_id, issue, diagnosis, result, user_id)


class RollbackWorkflow:
    """Workflow for rolling back failed self-healing attempts"""

    def __init__(self, workspace_id: Optional[UUID] = None):
        self.workspace_id = workspace_id

    async def execute(
        self,
        runbook: RunbookBase,
        failed_result: RunbookResult,
    ) -> bool:
        """
        Execute rollback of failed recovery attempt

        Returns True if rollback was successful, False otherwise
        """
        try:
            logger.info(f"Attempting rollback for {runbook.runbook_type}")

            # Call runbook's rollback method
            rollback_success = await runbook.rollback(failed_result)

            if rollback_success:
                logger.info(f"Rollback successful for {runbook.runbook_type}")
            else:
                logger.error(f"Rollback failed for {runbook.runbook_type}")

            return rollback_success

        except Exception as e:
            logger.error(f"Error during rollback: {e}")
            return False


class IncidentMemoryWorkflow:
    """Workflow for storing incident information in system memory"""

    def __init__(self, workspace_id: Optional[UUID] = None):
        self.workspace_id = workspace_id

    async def execute(
        self,
        incident_id: UUID,
        issue: IssueDetection,
        diagnosis: Dict[str, Any],
        result: RunbookResult,
    ) -> UUID:
        """
        Store incident information in memory system

        Memory includes:
        - Issue description
        - Diagnosis findings
        - Applied fixes
        - Outcomes
        - Recovery status
        """
        try:
            async with AsyncSessionLocal() as db:
                # Create memory record
                memory = Memory(
                    agent_id=SELF_HEALING_SYSTEM_AGENT_ID,
                    memory_type="incident",
                    content={
                        "incident_id": str(incident_id),
                        "issue_type": issue.issue_type,
                        "issue_description": issue.description,
                        "severity": issue.severity,
                        "affected_systems": issue.affected_systems,
                        "diagnosis": diagnosis,
                        "recovery_actions": [action for action in result.recovery_actions],
                        "success": result.success,
                        "execution_time": result.execution_time.isoformat(),
                    },
                    tags=[
                        issue.issue_type,
                        issue.severity,
                        "self_healing",
                        "incident",
                    ],
                    importance_score=0.9 if result.success else 1.0,
                )

                db.add(memory)
                await db.commit()
                await db.refresh(memory)

                logger.info(f"Created incident memory {memory.id} for incident {incident_id}")
                return memory.id

        except Exception as e:
            logger.error(f"Error creating incident memory: {e}")
            raise


class ExperienceRecordWorkflow:
    """Workflow for creating experience records from incidents"""

    def __init__(self, workspace_id: Optional[UUID] = None):
        self.workspace_id = workspace_id

    async def execute(
        self,
        incident_id: UUID,
        issue: IssueDetection,
        diagnosis: Dict[str, Any],
        result: RunbookResult,
        user_id: Optional[UUID],
    ) -> UUID:
        """
        Create experience record from incident for self-evolution

        Experience includes:
        - What issue occurred
        - What was diagnosed
        - What fix was applied
        - The outcome
        - Lessons learned
        """
        try:
            async with AsyncSessionLocal() as db:
                # Generate lessons learned
                lessons = self._generate_lessons_learned(issue, diagnosis, result)

                # Create experience record
                experience = ExperienceRecord(
                    workspace_id=self.workspace_id,
                    experience_type="incident_resolution",
                    context={
                        "incident_id": str(incident_id),
                        "issue_type": issue.issue_type,
                        "severity": issue.severity,
                        "affected_systems": issue.affected_systems,
                    },
                    action_taken={
                        "diagnosis": diagnosis,
                        "runbook_type": result.steps_executed[0].get("step") if result.steps_executed else "unknown",
                        "recovery_actions": result.recovery_actions,
                    },
                    outcome={
                        "success": result.success,
                        "status": result.status.value,
                        "error_message": result.error_message,
                    },
                    lessons_learned=lessons,
                    impact_score=0.9 if result.success else 1.0,
                    created_by=user_id,
                )

                db.add(experience)
                await db.commit()
                await db.refresh(experience)

                logger.info(
                    f"Created experience record {experience.id} for incident {incident_id}. "
                    f"Self-Evolution Agent will analyze this record from the database."
                )

                return experience.id

        except Exception as e:
            logger.error(f"Error creating experience record: {e}")
            raise

    def _generate_lessons_learned(
        self,
        issue: IssueDetection,
        diagnosis: Dict[str, Any],
        result: RunbookResult,
    ) -> str:
        """Generate lessons learned from incident"""
        lessons = []

        if result.success:
            lessons.append(
                f"Successfully resolved {issue.issue_type} using automated runbook. "
                f"Root cause was {diagnosis.get('root_cause', 'unknown')}."
            )

            if result.recovery_actions:
                actions = ", ".join([a.get("action", "unknown") for a in result.recovery_actions])
                lessons.append(f"Recovery actions taken: {actions}")

            lessons.append(
                "This incident pattern should be monitored for recurrence. "
                "Consider implementing preventive measures."
            )

        else:
            lessons.append(
                f"Failed to automatically resolve {issue.issue_type}. "
                f"Error: {result.error_message}"
            )

            lessons.append(
                "This runbook may need improvement or the issue requires manual intervention. "
                "Consider updating the runbook logic or adding new recovery steps."
            )

        return " ".join(lessons)
