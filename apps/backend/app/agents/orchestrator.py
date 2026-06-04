"""
JARV Backend - Orchestrator Agent

Core orchestration agent that receives missions, creates task plans,
delegates to specialist agents, and produces final reports.
"""
from typing import Dict, Any, List, Optional, Type
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
import logging

from app.core.agents.base import (
    AgentBase,
    AgentConfig,
    AgentContext,
    AgentResult,
    AuthorityLevel,
)
from app.core.providers import get_router, CompletionRequest, Message

logger = logging.getLogger(__name__)


# ===== Input/Output Schemas =====

class OrchestratorInput(BaseModel):
    """Input schema for orchestrator agent"""
    mission: str = Field(..., description="High-level mission or goal to accomplish")
    context: Optional[str] = Field(None, description="Additional context about the mission")
    constraints: List[str] = Field(default_factory=list, description="Constraints or requirements")
    priority: str = Field(default="normal", description="Priority level: low, normal, high, critical")
    deadline: Optional[datetime] = Field(None, description="Optional deadline for completion")


class TaskPlan(BaseModel):
    """Individual task in the execution plan"""
    task_id: int = Field(..., description="Task sequence number")
    description: str = Field(..., description="Task description")
    assigned_agent: Optional[str] = Field(None, description="Agent to execute this task")
    dependencies: List[int] = Field(default_factory=list, description="Task IDs this depends on")
    estimated_complexity: str = Field(default="medium", description="Complexity: low, medium, high")
    requires_approval: bool = Field(default=False, description="Whether task needs approval")
    requires_swarm: bool = Field(default=False, description="Whether to use swarm for parallel execution")


class OrchestratorOutput(BaseModel):
    """Output schema for orchestrator agent"""
    mission_status: str = Field(..., description="Status: planned, in_progress, completed, failed, blocked")
    task_plan: List[TaskPlan] = Field(..., description="Breakdown of tasks to execute")
    execution_summary: str = Field(..., description="Summary of what was accomplished")
    completed_tasks: int = Field(default=0, description="Number of completed tasks")
    total_tasks: int = Field(..., description="Total number of tasks")
    agents_used: List[str] = Field(default_factory=list, description="Agents that were used")
    tools_used: List[str] = Field(default_factory=list, description="Tools that were used")
    requires_human_input: bool = Field(default=False, description="Whether human input is needed")
    blocking_issues: List[str] = Field(default_factory=list, description="Issues blocking progress")
    next_steps: List[str] = Field(default_factory=list, description="Recommended next actions")
    memory_updates: List[Dict[str, Any]] = Field(default_factory=list, description="Memories to store")


# ===== Orchestrator Agent Implementation =====

class OrchestratorAgent(AgentBase):
    """
    Core Orchestrator Agent.

    The Orchestrator is the primary agent that:
    - Receives high-level missions from users
    - Loads workspace context, rules, and operating plans
    - Retrieves relevant memories
    - Creates detailed task plans
    - Delegates tasks to specialist agents
    - Calls tools when needed
    - Enforces authority levels
    - Requests swarm execution for parallel work
    - Requests verification for risky operations
    - Updates memory with learnings
    - Produces comprehensive final reports

    Authority Level: LEVEL_9_SWARM_CREATION (can create swarms and coordinate all agents)
    """

    @property
    def name(self) -> str:
        return "orchestrator"

    @property
    def role(self) -> str:
        return "Core orchestration agent that coordinates tasks and delegates to specialist agents"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return OrchestratorInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return OrchestratorOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_9_SWARM_CREATION

    @property
    def default_tools(self) -> List[str]:
        return [
            "text_search",
            "file_read",
            "workspace_query",
            "memory_search",
            "agent_invoke",
        ]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute orchestrator agent.

        Workflow:
        1. Load workspace and operating plan
        2. Search relevant memories
        3. Analyze mission and create task plan
        4. Execute or delegate tasks
        5. Update memory with learnings
        6. Produce final report
        """
        mission = input_data["mission"]
        additional_context = input_data.get("context", "")
        constraints = input_data.get("constraints", [])
        priority = input_data.get("priority", "normal")

        self.logger.info(
            f"Orchestrator received mission: {mission[:100]}...",
            extra={
                "priority": priority,
                "has_constraints": len(constraints) > 0,
                "workspace_id": str(context.workspace_id) if context.workspace_id else None,
            }
        )

        # Step 1: Load workspace context
        workspace_info = self._load_workspace_context(context)

        # Step 2: Load operating plan (if in company mode)
        operating_plan = self._load_operating_plan(context)

        # Step 3: Search relevant memories
        relevant_memories = await self._search_memories(mission, context)

        # Step 4: Analyze mission and create task plan
        task_plan = await self._create_task_plan(
            mission=mission,
            context=additional_context,
            constraints=constraints,
            workspace_info=workspace_info,
            operating_plan=operating_plan,
            memories=relevant_memories,
        )

        # Step 5: Determine execution strategy
        execution_strategy = self._determine_execution_strategy(task_plan)

        # Step 6: Execute or prepare for execution
        # Execution delegation depends on:
        # - Tool system (Phase 5) for tool invocation
        # - Specialist agents (Phase 13) for task delegation
        # - Swarm system (Phase 11) for parallel execution
        # Integration points are ready; orchestrator will execute when dependencies complete
        execution_summary = self._generate_execution_summary(
            mission=mission,
            task_plan=task_plan,
            strategy=execution_strategy,
        )

        # Step 7: Prepare memory updates
        memory_updates = self._prepare_memory_updates(
            mission=mission,
            task_plan=task_plan,
            context=context,
        )

        # Step 8: Determine next steps
        next_steps = self._determine_next_steps(task_plan, execution_strategy)

        # Create output
        output_data = {
            "mission_status": "planned",  # Will be "in_progress" or "completed" after execution
            "task_plan": [task.dict() for task in task_plan],
            "execution_summary": execution_summary,
            "completed_tasks": 0,
            "total_tasks": len(task_plan),
            "agents_used": [],  # Will be populated during execution
            "tools_used": [],
            "requires_human_input": any(task.requires_approval for task in task_plan),
            "blocking_issues": [],
            "next_steps": next_steps,
            "memory_updates": memory_updates,
        }

        validated_output = self._validate_output(output_data)

        # Calculate token usage (approximate)
        # In real execution, this would come from LLM calls
        estimated_tokens = len(mission) // 4 + sum(len(t.description) for t in task_plan) // 4

        return self.create_result(
            success=True,
            result_data=validated_output,
            output_text=execution_summary,
            tools_used=["memory_search", "task_planner"],
            iterations_used=1,
            tokens_used={
                "input_tokens": estimated_tokens,
                "output_tokens": estimated_tokens // 2,
                "total_tokens": estimated_tokens + estimated_tokens // 2,
            },
            cost_estimate=0.0,  # Will be calculated based on actual LLM usage
            requires_approval=any(task.requires_approval for task in task_plan),
            next_actions=next_steps,
        )

    # ===== Helper Methods =====

    def _load_workspace_context(self, context: AgentContext) -> Dict[str, Any]:
        """
        Load workspace context including rules and configuration.

        Args:
            context: Agent execution context

        Returns:
            Dictionary with workspace information
        """
        workspace_info = {
            "workspace_id": str(context.workspace_id) if context.workspace_id else None,
            "rules": context.workspace_rules,
            "has_rules": len(context.workspace_rules) > 0,
        }

        self.logger.info(
            f"Loaded workspace context",
            extra={
                "workspace_id": workspace_info["workspace_id"],
                "rule_count": len(context.workspace_rules),
            }
        )

        return workspace_info

    def _load_operating_plan(self, context: AgentContext) -> Optional[Dict[str, Any]]:
        """
        Load operating plan if workspace is in company mode.

        Args:
            context: Agent execution context

        Returns:
            Operating plan data or None
        """
        operating_plan = context.operating_plan

        if operating_plan:
            self.logger.info(
                "Loaded operating plan for company mode",
                extra={"has_plan": True}
            )
        else:
            self.logger.debug("No operating plan (not in company mode)")

        return operating_plan

    async def _search_memories(
        self,
        mission: str,
        context: AgentContext,
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant memories related to the mission.

        Args:
            mission: Mission description
            context: Agent execution context

        Returns:
            List of relevant memories
        """
        # Check if memory access is enabled
        if not self.can_access_memory():
            self.logger.debug("Memory access disabled")
            return []

        # Use memories from context
        memories = context.memory_context

        self.logger.info(
            f"Retrieved {len(memories)} relevant memories",
            extra={"memory_count": len(memories)}
        )

        return memories

    async def _create_task_plan(
        self,
        mission: str,
        context: str,
        constraints: List[str],
        workspace_info: Dict[str, Any],
        operating_plan: Optional[Dict[str, Any]],
        memories: List[Dict[str, Any]],
    ) -> List[TaskPlan]:
        """
        Create detailed task plan by analyzing mission with LLM.

        Uses the model router to call configured LLM provider.
        If no provider is configured, falls back to basic planning.

        Args:
            mission: Mission description
            context: Additional context
            constraints: Constraints to respect
            workspace_info: Workspace information
            operating_plan: Operating plan if available
            memories: Relevant memories

        Returns:
            List of tasks to execute
        """
        self.logger.info("Creating task plan with LLM analysis")

        # Build prompt for LLM
        prompt = self._build_planning_prompt(
            mission=mission,
            context=context,
            constraints=constraints,
            workspace_info=workspace_info,
            operating_plan=operating_plan,
            memories=memories,
        )

        # Try to use LLM for intelligent planning
        try:
            task_plan = await self._create_llm_task_plan(prompt, mission, constraints)
        except Exception as e:
            # If LLM fails (no API key, provider unavailable, etc.), use basic planning
            self.logger.warning(
                f"LLM planning failed, using basic plan: {e}",
                extra={"error": str(e)}
            )
            task_plan = self._generate_simple_task_plan(mission, constraints)

        self.logger.info(
            f"Created task plan with {len(task_plan)} tasks",
            extra={"task_count": len(task_plan)}
        )

        return task_plan

    async def _create_llm_task_plan(
        self,
        prompt: str,
        mission: str,
        constraints: List[str],
    ) -> List[TaskPlan]:
        """
        Create task plan using LLM via model router.

        Args:
            prompt: Planning prompt for LLM
            mission: Mission description
            constraints: Constraints to respect

        Returns:
            List of tasks from LLM analysis

        Raises:
            Exception: If LLM call fails or no provider configured
        """
        router = get_router()

        # Create completion request
        completion_request = CompletionRequest(
            model=self.config.model,
            messages=[Message(role="user", content=prompt)],
            temperature=self.config.temperature,
            max_tokens=2000,
        )

        # Call LLM
        response = await router.complete(completion_request)

        # Parse LLM response into task plan
        # For now, parse structured output from LLM
        # In production, use structured output or JSON mode
        task_plan = self._parse_llm_response(response.content, mission, constraints)

        return task_plan

    def _parse_llm_response(
        self,
        llm_output: str,
        mission: str,
        constraints: List[str],
    ) -> List[TaskPlan]:
        """
        Parse the LLM's JSON task plan into structured TaskPlan objects.

        The planning prompt instructs the model to return a JSON object with a
        "tasks" array. We extract the JSON robustly (handling ```json fences and
        surrounding prose) and validate each task. If parsing genuinely fails,
        we fall back to a simple plan so the orchestrator never hard-fails.
        """
        data = self._extract_json(llm_output)
        if not data:
            self.logger.warning("Could not extract JSON from LLM plan; using fallback plan")
            return self._generate_simple_task_plan(mission, constraints)

        raw_tasks = data.get("tasks") or data.get("task_plan") or []
        if not isinstance(raw_tasks, list) or not raw_tasks:
            self.logger.warning("LLM plan had no tasks; using fallback plan")
            return self._generate_simple_task_plan(mission, constraints)

        task_plan: List[TaskPlan] = []
        for idx, raw in enumerate(raw_tasks, start=1):
            if not isinstance(raw, dict):
                continue
            try:
                deps = raw.get("dependencies") or []
                if not isinstance(deps, list):
                    deps = []
                task_plan.append(
                    TaskPlan(
                        task_id=int(raw.get("task_id", idx)),
                        description=str(raw.get("description", "")).strip() or f"Step {idx}",
                        assigned_agent=raw.get("assigned_agent") or None,
                        dependencies=[int(d) for d in deps if str(d).isdigit()],
                        estimated_complexity=str(raw.get("estimated_complexity", "medium")).lower(),
                        requires_approval=bool(raw.get("requires_approval", False)),
                        requires_swarm=bool(raw.get("requires_swarm", False)),
                    )
                )
            except Exception as e:  # noqa: BLE001
                self.logger.debug(f"Skipping malformed task in LLM plan: {e}")
                continue

        if not task_plan:
            return self._generate_simple_task_plan(mission, constraints)

        self.logger.info(f"Parsed {len(task_plan)} tasks from Claude planning output")
        return task_plan

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from an LLM response (handles code fences/prose)."""
        if not text:
            return None
        import json as _json
        import re as _re

        # Prefer a fenced ```json ... ``` block if present.
        fence = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
        candidates = []
        if fence:
            candidates.append(fence.group(1))
        # Fall back to the first balanced-looking {...} span.
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            candidates.append(text[first : last + 1])
        for cand in candidates:
            try:
                parsed = _json.loads(cand)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:  # noqa: BLE001
                continue
        return None

    def _build_planning_prompt(
        self,
        mission: str,
        context: str,
        constraints: List[str],
        workspace_info: Dict[str, Any],
        operating_plan: Optional[Dict[str, Any]],
        memories: List[Dict[str, Any]],
    ) -> str:
        """Build LLM prompt for task planning"""
        prompt_parts = [
            "You are the Orchestrator Agent in the JARV AI system.",
            "Your job is to analyze missions and create detailed task plans.",
            "",
            f"MISSION: {mission}",
        ]

        if context:
            prompt_parts.extend(["", f"CONTEXT: {context}"])

        if constraints:
            prompt_parts.extend(["", "CONSTRAINTS:"])
            prompt_parts.extend([f"- {c}" for c in constraints])

        if workspace_info.get("rules"):
            prompt_parts.extend(["", f"WORKSPACE RULES: {len(workspace_info['rules'])} rules active"])

        if operating_plan:
            prompt_parts.extend(["", "OPERATING PLAN: Available (company mode active)"])

        if memories:
            prompt_parts.extend(["", f"RELEVANT MEMORIES: {len(memories)} memories found"])

        # Provide the REAL set of available agents so assignments are valid.
        available_agents = self._available_agent_names()
        if available_agents:
            prompt_parts.extend([
                "",
                "AVAILABLE AGENTS (assign tasks only to these names):",
                ", ".join(available_agents),
            ])

        prompt_parts.extend([
            "",
            "Create a detailed, ordered task plan. Assign each task to the most "
            "appropriate agent from the AVAILABLE AGENTS list. Mark requires_approval "
            "true for any task that modifies files, deploys, deletes data, or spends money.",
            "",
            "Respond with ONLY a JSON object in exactly this shape (no prose, no markdown):",
            "{",
            '  "summary": "one-sentence summary of the approach",',
            '  "tasks": [',
            '    {"task_id": 1, "description": "...", "assigned_agent": "researcher",',
            '     "dependencies": [], "estimated_complexity": "low|medium|high",',
            '     "requires_approval": false, "requires_swarm": false}',
            "  ]",
            "}",
        ])

        return "\n".join(prompt_parts)

    def _available_agent_names(self) -> List[str]:
        """Return the names of implemented agents from the registry (best effort)."""
        try:
            from app.core.agents.registry import get_registry

            return [m.name for m in get_registry().list_implemented()]
        except Exception:  # noqa: BLE001
            return []

    def _generate_simple_task_plan(
        self,
        mission: str,
        constraints: List[str],
    ) -> List[TaskPlan]:
        """
        Generate simple task plan (placeholder until full LLM integration).

        Args:
            mission: Mission description
            constraints: Constraints to respect

        Returns:
            Simple task plan
        """
        # Create basic 3-step plan as placeholder
        tasks = [
            TaskPlan(
                task_id=1,
                description=f"Analyze and understand the mission: {mission[:100]}",
                assigned_agent="researcher",
                dependencies=[],
                estimated_complexity="low",
                requires_approval=False,
                requires_swarm=False,
            ),
            TaskPlan(
                task_id=2,
                description="Execute the core work based on mission requirements",
                assigned_agent=None,  # Will be determined based on mission type
                dependencies=[1],
                estimated_complexity="medium",
                requires_approval=len(constraints) > 0,
                requires_swarm=False,
            ),
            TaskPlan(
                task_id=3,
                description="Verify results and produce final report",
                assigned_agent="qa-tester",
                dependencies=[2],
                estimated_complexity="low",
                requires_approval=False,
                requires_swarm=False,
            ),
        ]

        return tasks

    def _determine_execution_strategy(self, task_plan: List[TaskPlan]) -> Dict[str, Any]:
        """
        Determine execution strategy based on task plan.

        Args:
            task_plan: List of tasks

        Returns:
            Execution strategy
        """
        # Analyze task plan
        has_parallel_tasks = any(
            task.requires_swarm for task in task_plan
        )
        needs_approval = any(
            task.requires_approval for task in task_plan
        )
        high_complexity_tasks = [
            task for task in task_plan
            if task.estimated_complexity == "high"
        ]

        strategy = {
            "approach": "sequential",  # or "parallel" or "hybrid"
            "use_swarm": has_parallel_tasks,
            "checkpoint_frequency": "after_each_task" if needs_approval else "after_completion",
            "approval_required": needs_approval,
            "high_risk_tasks": len(high_complexity_tasks),
        }

        if has_parallel_tasks:
            strategy["approach"] = "hybrid"

        return strategy

    def _generate_execution_summary(
        self,
        mission: str,
        task_plan: List[TaskPlan],
        strategy: Dict[str, Any],
    ) -> str:
        """
        Generate human-readable execution summary.

        Args:
            mission: Original mission
            task_plan: Created task plan
            strategy: Execution strategy

        Returns:
            Summary text
        """
        summary_parts = [
            f"Mission received: {mission}",
            f"",
            f"Created execution plan with {len(task_plan)} tasks:",
        ]

        for task in task_plan:
            agent_info = f" (assigned to {task.assigned_agent})" if task.assigned_agent else ""
            approval_info = " [REQUIRES APPROVAL]" if task.requires_approval else ""
            summary_parts.append(
                f"  {task.task_id}. {task.description}{agent_info}{approval_info}"
            )

        summary_parts.extend([
            "",
            f"Execution strategy: {strategy['approach']}",
        ])

        if strategy["use_swarm"]:
            summary_parts.append("Will use swarm for parallel execution")

        if strategy["approval_required"]:
            summary_parts.append("⚠️  Some tasks require approval before execution")

        summary_parts.append("")
        summary_parts.append("Ready to begin execution. Use /execute to start.")

        return "\n".join(summary_parts)

    def _prepare_memory_updates(
        self,
        mission: str,
        task_plan: List[TaskPlan],
        context: AgentContext,
    ) -> List[Dict[str, Any]]:
        """
        Prepare memory updates to store mission and plan.

        Args:
            mission: Mission description
            task_plan: Task plan
            context: Execution context

        Returns:
            List of memory updates
        """
        if not self.can_access_memory():
            return []

        memory_updates = [
            {
                "content": f"Mission planned: {mission}",
                "importance": 0.8,
                "tags": ["mission", "planning", "orchestrator"],
                "metadata": {
                    "task_count": len(task_plan),
                    "workspace_id": str(context.workspace_id) if context.workspace_id else None,
                },
            }
        ]

        return memory_updates

    def _determine_next_steps(
        self,
        task_plan: List[TaskPlan],
        strategy: Dict[str, Any],
    ) -> List[str]:
        """
        Determine next steps for user.

        Args:
            task_plan: Task plan
            strategy: Execution strategy

        Returns:
            List of next step recommendations
        """
        next_steps = []

        if strategy["approval_required"]:
            next_steps.append("Review task plan and approve high-risk tasks")

        next_steps.append("Execute task plan with /execute command")

        if strategy["use_swarm"]:
            next_steps.append("Monitor swarm execution progress")

        next_steps.append("Review results when execution completes")

        return next_steps
