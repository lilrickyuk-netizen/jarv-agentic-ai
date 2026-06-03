"""
JARV Backend - Workspace Rules Engine

Evaluates and enforces workspace-specific rules.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class RuleCondition(BaseModel):
    """Rule condition evaluation"""
    field: str
    operator: str  # eq, ne, gt, lt, gte, lte, in, contains, matches
    value: Any
    case_sensitive: bool = True


class RuleAction(BaseModel):
    """Rule action specification"""
    action_type: str  # allow, deny, require_approval, modify, notify
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RuleEvaluation(BaseModel):
    """Result of rule evaluation"""
    rule_id: UUID
    rule_name: str
    matched: bool
    actions_triggered: List[RuleAction]
    evaluation_context: Dict[str, Any]
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkspaceRule(BaseModel):
    """Workspace rule definition"""
    id: UUID
    rule_name: str
    rule_type: str
    description: Optional[str]
    rule_content: Dict[str, Any]
    conditions: Optional[Dict[str, Any]]
    actions: Optional[Dict[str, Any]]
    is_active: bool
    priority: int


class RulesEngine:
    """
    Evaluates and enforces workspace-specific rules.

    Provides rule evaluation, condition matching, and action execution.
    """

    def __init__(self):
        """Initialize rules engine"""
        self.logger = logging.getLogger("workspaces.rules")

    async def get_workspace_rules(
        self,
        workspace_id: UUID,
        rule_type: Optional[str] = None,
        active_only: bool = True,
    ) -> List[WorkspaceRule]:
        """
        Get rules for a workspace.

        In production: Query WorkspaceRule table.

        Args:
            workspace_id: Workspace ID
            rule_type: Optional rule type filter
            active_only: Only return active rules

        Returns:
            List of rules
        """
        try:
            # In production: Query database
            # from app.models.workspace_rules import WorkspaceRule as DBRule
            # from app.core.database import get_db
            # async with get_db() as db:
            #     query = select(DBRule).where(DBRule.workspace_id == workspace_id)
            #
            #     if active_only:
            #         query = query.where(DBRule.is_active == True)
            #     if rule_type:
            #         query = query.where(DBRule.rule_type == rule_type)
            #
            #     results = await db.execute(
            #         query.order_by(DBRule.priority.desc(), DBRule.created_at)
            #     )
            #
            #     return [WorkspaceRule.from_orm(row) for row in results]

            self.logger.debug(
                f"Retrieved rules for workspace {workspace_id}",
                extra={"workspace_id": str(workspace_id), "rule_type": rule_type}
            )

            return []

        except Exception as e:
            self.logger.error(
                f"Failed to get workspace rules: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            return []

    def evaluate_condition(
        self,
        condition: RuleCondition,
        context: Dict[str, Any],
    ) -> bool:
        """
        Evaluate a single condition against context.

        Args:
            condition: Condition to evaluate
            context: Context data

        Returns:
            True if condition matches
        """
        try:
            # Get field value from context
            field_value = context.get(condition.field)

            if field_value is None:
                return False

            # Apply case sensitivity for strings
            if isinstance(field_value, str) and not condition.case_sensitive:
                field_value = field_value.lower()
                if isinstance(condition.value, str):
                    condition.value = condition.value.lower()

            # Evaluate operator
            if condition.operator == "eq":
                return field_value == condition.value
            elif condition.operator == "ne":
                return field_value != condition.value
            elif condition.operator == "gt":
                return field_value > condition.value
            elif condition.operator == "lt":
                return field_value < condition.value
            elif condition.operator == "gte":
                return field_value >= condition.value
            elif condition.operator == "lte":
                return field_value <= condition.value
            elif condition.operator == "in":
                return field_value in condition.value
            elif condition.operator == "contains":
                return condition.value in field_value
            elif condition.operator == "matches":
                import re
                return bool(re.match(condition.value, str(field_value)))
            else:
                self.logger.warning(
                    f"Unknown operator: {condition.operator}",
                    extra={"operator": condition.operator}
                )
                return False

        except Exception as e:
            self.logger.error(
                f"Failed to evaluate condition: {e}",
                extra={"condition": condition.dict()},
                exc_info=True
            )
            return False

    async def evaluate_rule(
        self,
        rule: WorkspaceRule,
        context: Dict[str, Any],
    ) -> RuleEvaluation:
        """
        Evaluate a rule against context.

        Args:
            rule: Rule to evaluate
            context: Context data

        Returns:
            RuleEvaluation result
        """
        try:
            # Check if rule is active
            if not rule.is_active:
                return RuleEvaluation(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    matched=False,
                    actions_triggered=[],
                    evaluation_context=context,
                )

            # Evaluate conditions
            matched = True
            if rule.conditions:
                # Handle different condition structures
                if "all" in rule.conditions:
                    # All conditions must match (AND)
                    for cond_data in rule.conditions["all"]:
                        cond = RuleCondition(**cond_data)
                        if not self.evaluate_condition(cond, context):
                            matched = False
                            break

                elif "any" in rule.conditions:
                    # Any condition must match (OR)
                    matched = False
                    for cond_data in rule.conditions["any"]:
                        cond = RuleCondition(**cond_data)
                        if self.evaluate_condition(cond, context):
                            matched = True
                            break

                elif "none" in rule.conditions:
                    # No condition must match (NOT)
                    for cond_data in rule.conditions["none"]:
                        cond = RuleCondition(**cond_data)
                        if self.evaluate_condition(cond, context):
                            matched = False
                            break

            # Extract actions if matched
            actions_triggered = []
            if matched and rule.actions:
                if isinstance(rule.actions, list):
                    actions_triggered = [RuleAction(**action) for action in rule.actions]
                elif isinstance(rule.actions, dict) and "actions" in rule.actions:
                    actions_triggered = [
                        RuleAction(**action) for action in rule.actions["actions"]
                    ]

            evaluation = RuleEvaluation(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                matched=matched,
                actions_triggered=actions_triggered,
                evaluation_context=context,
            )

            self.logger.debug(
                f"Evaluated rule '{rule.rule_name}': {'matched' if matched else 'not matched'}",
                extra={
                    "rule_id": str(rule.id),
                    "rule_name": rule.rule_name,
                    "matched": matched,
                    "actions_count": len(actions_triggered),
                }
            )

            return evaluation

        except Exception as e:
            self.logger.error(
                f"Failed to evaluate rule: {e}",
                extra={"rule_id": str(rule.id)},
                exc_info=True
            )
            return RuleEvaluation(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                matched=False,
                actions_triggered=[],
                evaluation_context=context,
            )

    async def evaluate_workspace_rules(
        self,
        workspace_id: UUID,
        context: Dict[str, Any],
        rule_type: Optional[str] = None,
    ) -> List[RuleEvaluation]:
        """
        Evaluate all workspace rules against context.

        Args:
            workspace_id: Workspace ID
            context: Context data
            rule_type: Optional rule type filter

        Returns:
            List of rule evaluations
        """
        try:
            # Get workspace rules
            rules = await self.get_workspace_rules(
                workspace_id=workspace_id,
                rule_type=rule_type,
                active_only=True,
            )

            # Evaluate each rule
            evaluations = []
            for rule in rules:
                evaluation = await self.evaluate_rule(rule, context)
                if evaluation.matched:
                    evaluations.append(evaluation)

            self.logger.info(
                f"Evaluated {len(rules)} rules, {len(evaluations)} matched",
                extra={
                    "workspace_id": str(workspace_id),
                    "total_rules": len(rules),
                    "matched_rules": len(evaluations),
                }
            )

            return evaluations

        except Exception as e:
            self.logger.error(
                f"Failed to evaluate workspace rules: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            return []

    async def create_rule(
        self,
        workspace_id: UUID,
        rule_name: str,
        rule_type: str,
        rule_content: Dict[str, Any],
        description: Optional[str] = None,
        conditions: Optional[Dict[str, Any]] = None,
        actions: Optional[Dict[str, Any]] = None,
        priority: int = 5,
        created_by: Optional[UUID] = None,
    ) -> UUID:
        """
        Create a new workspace rule.

        In production: Insert into WorkspaceRule table.

        Args:
            workspace_id: Workspace ID
            rule_name: Rule name
            rule_type: Rule type
            rule_content: Rule content
            description: Optional description
            conditions: Rule conditions
            actions: Rule actions
            priority: Rule priority (higher = evaluated first)
            created_by: Creator user ID

        Returns:
            Rule ID
        """
        try:
            # In production: Insert into database
            # from app.models.workspace_rules import WorkspaceRule as DBRule
            # from app.core.database import get_db
            # async with get_db() as db:
            #     rule = DBRule(
            #         workspace_id=workspace_id,
            #         rule_name=rule_name,
            #         rule_type=rule_type,
            #         description=description,
            #         rule_content=rule_content,
            #         conditions=conditions,
            #         actions=actions,
            #         priority=priority,
            #         created_by=created_by,
            #     )
            #     db.add(rule)
            #     await db.commit()
            #     rule_id = rule.id

            # Placeholder
            from uuid import uuid4
            rule_id = uuid4()

            self.logger.info(
                f"Created rule: {rule_name}",
                extra={
                    "rule_id": str(rule_id),
                    "workspace_id": str(workspace_id),
                    "rule_type": rule_type,
                }
            )

            return rule_id

        except Exception as e:
            self.logger.error(
                f"Failed to create rule: {e}",
                extra={"workspace_id": str(workspace_id), "rule_name": rule_name},
                exc_info=True
            )
            raise

    async def update_rule(
        self,
        rule_id: UUID,
        updates: Dict[str, Any],
        create_version: bool = True,
        changed_by: Optional[UUID] = None,
    ) -> bool:
        """
        Update a workspace rule.

        In production: Update WorkspaceRule and create version.

        Args:
            rule_id: Rule ID
            updates: Fields to update
            create_version: Whether to create version history
            changed_by: User making the change

        Returns:
            True if successful
        """
        try:
            # In production: Update database and create version
            # from app.models.workspace_rules import (
            #     WorkspaceRule as DBRule,
            #     WorkspaceRuleVersion
            # )
            # from app.core.database import get_db
            # async with get_db() as db:
            #     rule = await db.get(DBRule, rule_id)
            #     if not rule:
            #         return False
            #
            #     if create_version:
            #         # Create version snapshot
            #         version = WorkspaceRuleVersion(
            #             rule_id=rule_id,
            #             version_number=rule.current_version,
            #             rule_content=rule.rule_content,
            #             conditions=rule.conditions,
            #             actions=rule.actions,
            #             changed_by=changed_by,
            #         )
            #         db.add(version)
            #         rule.current_version += 1
            #
            #     # Update rule
            #     for key, value in updates.items():
            #         setattr(rule, key, value)
            #
            #     await db.commit()

            self.logger.info(
                f"Updated rule {rule_id}",
                extra={"rule_id": str(rule_id), "create_version": create_version}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to update rule: {e}",
                extra={"rule_id": str(rule_id)},
                exc_info=True
            )
            return False

    async def delete_rule(self, rule_id: UUID) -> bool:
        """
        Delete a workspace rule.

        In production: Delete from WorkspaceRule table.

        Args:
            rule_id: Rule ID

        Returns:
            True if successful
        """
        try:
            # In production: Delete from database
            # from app.models.workspace_rules import WorkspaceRule as DBRule
            # from app.core.database import get_db
            # async with get_db() as db:
            #     rule = await db.get(DBRule, rule_id)
            #     if rule:
            #         await db.delete(rule)
            #         await db.commit()
            #         return True

            self.logger.info(
                f"Deleted rule {rule_id}",
                extra={"rule_id": str(rule_id)}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to delete rule: {e}",
                extra={"rule_id": str(rule_id)},
                exc_info=True
            )
            return False


# Global rules engine
_rules_engine = RulesEngine()


async def evaluate_rule(
    rule: WorkspaceRule,
    context: Dict[str, Any],
) -> RuleEvaluation:
    """
    Global function to evaluate a rule.

    Args:
        rule: Rule to evaluate
        context: Context data

    Returns:
        RuleEvaluation result
    """
    return await _rules_engine.evaluate_rule(rule, context)
