"""
JARV Backend - Example Agent

Simple example agent demonstrating AgentBase usage.
This serves as a template for implementing new agents.
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field

from app.core.agents.base import (
    AgentBase,
    AgentConfig,
    AgentContext,
    AgentResult,
    AuthorityLevel,
)


# ===== Input/Output Schemas =====

class ExampleAgentInput(BaseModel):
    """Input schema for example agent"""
    task_description: str = Field(..., description="Description of task to perform")
    additional_context: str = Field(default="", description="Additional context")


class ExampleAgentOutput(BaseModel):
    """Output schema for example agent"""
    status: str = Field(..., description="Execution status")
    message: str = Field(..., description="Result message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")


# ===== Agent Implementation =====

class ExampleAgent(AgentBase):
    """
    Example agent demonstrating AgentBase usage.

    This agent shows how to:
    - Define input/output schemas
    - Implement required properties
    - Implement run() method
    - Use logging and error handling
    - Create standardized results
    """

    @property
    def name(self) -> str:
        return "example-agent"

    @property
    def role(self) -> str:
        return "Demonstrates agent base class usage and serves as implementation template"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExampleAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExampleAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        # This agent only needs basic tools
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def default_tools(self) -> list[str]:
        # This agent doesn't require specific tools
        return []

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute example agent.

        This demonstrates the basic structure of agent execution:
        1. Log start of execution
        2. Access input data
        3. Use context information
        4. Perform agent logic
        5. Create and return result

        Args:
            input_data: Validated input data
            context: Execution context

        Returns:
            AgentResult with execution results
        """
        # Log execution details
        self.logger.info(
            f"Executing {self.name} with task: {input_data.get('task_description')}",
            extra={
                "workspace_id": str(context.workspace_id) if context.workspace_id else None,
            }
        )

        # Access input data
        task_description = input_data["task_description"]
        additional_context = input_data.get("additional_context", "")

        # Check memory access (if needed)
        if self.can_access_memory() and context.memory_context:
            self.logger.info(
                f"Loaded {len(context.memory_context)} memory items",
                extra={"memory_count": len(context.memory_context)}
            )

        # Simulate agent work
        # In a real agent, this would:
        # - Call LLM with prompts
        # - Use tools via tool system
        # - Access memory system
        # - Make decisions and take actions

        result_message = f"Successfully processed task: {task_description}"
        if additional_context:
            result_message += f" (with context: {additional_context})"

        # Validate output
        output_data = {
            "status": "completed",
            "message": result_message,
            "details": {
                "task_length": len(task_description),
                "had_context": bool(additional_context),
                "workspace_id": str(context.workspace_id) if context.workspace_id else None,
            }
        }
        validated_output = self._validate_output(output_data)

        # Create result
        return self.create_result(
            success=True,
            result_data=validated_output,
            output_text=result_message,
            tools_used=[],  # No tools used in this example
            iterations_used=1,
            tokens_used={
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
            cost_estimate=0.0,
        )


# ===== Usage Example =====

async def example_usage():
    """
    Example of how to use an agent.

    This demonstrates the complete agent lifecycle:
    1. Create agent configuration
    2. Instantiate agent
    3. Prepare execution context
    4. Execute agent
    5. Handle results
    """
    # 1. Create agent configuration
    config = AgentConfig(
        authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS,
        allowed_tools=["text_search", "file_read"],
        enable_memory=True,
        model="claude-sonnet-4-6",
        temperature=0.7,
    )

    # 2. Instantiate agent
    agent = ExampleAgent(config)

    # 3. Prepare execution context
    context = AgentContext(
        workspace_id=None,  # Would be UUID in real usage
        user_id=None,
        session_id=None,
        memory_context=[],
        workspace_rules=[],
    )

    # 4. Execute agent
    input_data = {
        "task_description": "Example task to demonstrate agent execution",
        "additional_context": "This is a test run",
    }

    result = await agent.execute(input_data, context)

    # 5. Handle results
    if result.success:
        print(f"✅ Agent succeeded: {result.output_text}")
        print(f"   Execution time: {result.execution_time_seconds:.2f}s")
        print(f"   Result data: {result.result_data}")
    else:
        print(f"❌ Agent failed: {result.error_message}")

    return result


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
