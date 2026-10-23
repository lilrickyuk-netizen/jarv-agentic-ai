"""Behavioral tests for persisted experience logging and retrieval."""
import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.self_evolution import ExperienceRecord
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.experience.logging import (
    ExperienceLogFailureTool,
    ExperienceLogSuccessTool,
    ExperienceRateActionTool,
)
from app.tools.experience.query import ExperienceQueryPatternTool
from app.tools.experience.query import ExperienceCompareApproachesTool, ExperienceGetSuggestionsTool
from app.tools.experience.management import (
    ExperienceAnalyzeTool,
    ExperienceConsolidateTool,
    ExperienceExportTool,
    ExperienceImportTool,
    ExperiencePruneTool,
    ExperienceVisualizeTool,
)
from tests.conftest import AsyncTestingSessionLocal


def _tool(tool_class):
    return tool_class(ToolConfig(authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE))


async def _seed_context(session):
    user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
    session.add(User(
        id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
        password_hash="test", is_active=True, is_admin=False,
    ))
    session.add(Workspace(
        id=workspace_id, owner_id=user_id, name="Experience scope", slug=f"exp-{workspace_id.hex[:8]}",
        description="", workspace_type="test", authority_level=6, is_active=True,
    ))
    session.add(Agent(
        id=agent_id, name="research", agent_type="research", workspace_id=workspace_id,
        is_active=True, authority_level=6, allowed_tools=[], blocked_tools=[], config={},
        model_provider="test", model_name="test",
    ))
    await session.commit()
    return ToolContext(user_id=user_id, workspace_id=workspace_id, agent_id=agent_id,
                       db_session=session)


@pytest.mark.integration
def test_experience_success_failure_and_rate_are_persisted_and_unvalidated():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            context = await _seed_context(session)
            common = {
                "title": "Bounded retries",
                "situation": "Transient network failures",
                "action_taken": "Retry with jitter and cap attempts",
                "result": "The request completed after retry",
                "lesson_learned": "Use bounded jittered backoff",
                "applicable_contexts": ["network", "retry"],
            }
            success = await _tool(ExperienceLogSuccessTool).run(common, context)
            failed = await _tool(ExperienceLogFailureTool).run({
                **common, "title": "Unbounded retries", "result": "The service remained overloaded",
            }, context)
            rated = await _tool(ExperienceRateActionTool).run({
                "experience_id": success.result_data["experience_id"],
                "rating": 0.9,
                "was_successful": True,
                "notes": "Verified with local replay",
            }, context)
            query = await _tool(ExperienceQueryPatternTool).run({
                "context": "network retry", "min_confidence": 0.5,
            }, context)
            suggestions_before_verification = await _tool(ExperienceGetSuggestionsTool).run({
                "current_situation": "Transient network failures",
                "goal": "robust retries",
            }, context)
            success_record = (await session.execute(select(ExperienceRecord).where(
                ExperienceRecord.id == UUID(success.result_data["experience_id"])
            ))).scalar_one()
            success_record.is_validated = True
            success_record.success_rate = 1.0
            await session.flush()
            suggestions_after_verification = await _tool(ExperienceGetSuggestionsTool).run({
                "current_situation": "Transient network failures",
                "goal": "robust retries",
            }, context)
            comparison = await _tool(ExperienceCompareApproachesTool).run({
                "approach_a_id": success.result_data["experience_id"],
                "approach_b_id": failed.result_data["experience_id"],
            }, context)
            records = (await session.execute(
                select(ExperienceRecord).order_by(ExperienceRecord.title)
            )).scalars().all()
            return (success, failed, rated, query, suggestions_before_verification,
                    suggestions_after_verification, comparison, records)

    (success, failed, rated, query, suggestions_before, suggestions_after,
     comparison, records) = asyncio.run(run())
    assert success.success is True and failed.success is True
    assert rated.success is True and rated.result_data["times_applied"] == 1
    assert query.success is True and query.result_data["count"] == 2
    assert suggestions_before.success is True and suggestions_before.result_data["count"] == 0
    assert suggestions_after.success is True and suggestions_after.result_data["count"] == 1
    assert suggestions_after.result_data["suggestions"][0]["provenance"] == "verified_outcome"
    assert comparison.success is True, comparison.error_message
    assert comparison.result_data["comparison"]["recommendation"] == "insufficient_verified_evidence"
    assert next(record for record in records if record.outcome == "success").is_validated is True
    assert next(record for record in records if record.outcome == "failure").is_validated is False
    assert {record.outcome for record in records} == {"success", "failure"}
    assert next(record for record in records if record.outcome == "success").success_rate == 1.0


@pytest.mark.integration
def test_experience_management_tools_use_persisted_records_and_approval():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            context = await _seed_context(session)
            common = {
                "situation": "database timeout recovery",
                "action_taken": "Retry with bounded jitter",
                "result": "Recovered after retry",
                "lesson_learned": "Use bounded jitter retries for database timeout recovery",
                "applicable_contexts": ["database", "retry"],
            }
            await _tool(ExperienceLogSuccessTool).run(
                {**common, "title": "Retry recovery"}, context)
            await _tool(ExperienceLogSuccessTool).run(
                {**common, "title": "Retry recovery duplicate"}, context)
            rows = (await session.execute(select(ExperienceRecord))).scalars().all()
            for row in rows:
                row.is_validated = True
                row.success_rate = 1.0
            await session.flush()

            exported = await _tool(ExperienceExportTool).run({"format": "json"}, context)
            imported = await _tool(ExperienceImportTool).run({
                "import_data": exported.result_data["export_data"],
                "merge_strategy": "create_new",
            }, context)
            analysis = await _tool(ExperienceAnalyzeTool).run({}, context)
            visualization = await _tool(ExperienceVisualizeTool).run({
                "visualization_type": "distribution",
            }, context)
            preview = await _tool(ExperienceConsolidateTool).run({
                "similarity_threshold": 0.8, "dry_run": True,
            }, context)
            unauthorized_prune = await _tool(ExperiencePruneTool).run({
                "inactive_only": False, "min_confidence": 1.0, "dry_run": False,
            }, context)
            rows[0].is_active = False
            await session.flush()
            prune_preview = await _tool(ExperiencePruneTool).run({
                "inactive_only": True, "dry_run": True,
            }, context)
            approved_context = ToolContext(
                user_id=context.user_id, workspace_id=context.workspace_id,
                agent_id=context.agent_id, db_session=session,
                approval_granted=True, approved_tools=["experience_prune"],
            )
            pruned = await _tool(ExperiencePruneTool).run({
                "inactive_only": True, "dry_run": False,
            }, approved_context)
            return exported, imported, analysis, visualization, preview, unauthorized_prune, prune_preview, pruned

    exported, imported, analysis, visualization, preview, unauthorized_prune, prune_preview, pruned = asyncio.run(run())
    assert exported.success is True and exported.result_data["count"] == 2
    assert imported.success is True and imported.result_data["imported_count"] == 2
    assert analysis.success is True and analysis.result_data["total_experiences"] == 4
    assert visualization.success is True and visualization.result_data["data_points"] > 0
    assert preview.success is True and preview.result_data["consolidated_count"] == 2
    assert unauthorized_prune.success is False
    assert prune_preview.success is True and prune_preview.result_data["would_prune_count"] == 1
    assert pruned.success is True and pruned.result_data["actually_pruned_count"] == 1