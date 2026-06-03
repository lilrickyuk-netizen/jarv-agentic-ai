# JARV Agent System

## Overview

The JARV Agent System provides a standardized framework for creating and managing AI agents with consistent interfaces, logging, error handling, and authority management.

## Architecture

### AgentBase Abstract Class

All agents inherit from `AgentBase`, which provides:

- **Standardized Interface**: Consistent input/output via Pydantic schemas
- **Authority Management**: 11-level authority system (0-10)
- **Tool Management**: Control which tools agents can use
- **Memory Access**: Optional memory system integration
- **Logging**: Structured logging for all agent actions
- **Error Handling**: Custom exception hierarchy
- **Validation**: Automatic input/output validation

### Authority Levels

```python
LEVEL_0_READ_ONLY = 0           # Can only read information
LEVEL_1_BASIC_TOOLS = 1         # Can use basic tools
LEVEL_2_FILE_OPERATIONS = 2     # Can read/write files
LEVEL_3_CODE_EXECUTION = 3      # Can execute code
LEVEL_4_SYSTEM_CHANGES = 4      # Can modify system settings
LEVEL_5_NETWORK_ACCESS = 5      # Can make network requests
LEVEL_6_DATABASE_WRITE = 6      # Can write to database
LEVEL_7_DEPLOYMENT = 7          # Can deploy applications
LEVEL_8_FINANCIAL = 8           # Can handle financial operations
LEVEL_9_SWARM_CREATION = 9      # Can create agent swarms
LEVEL_10_FULL_AUTONOMY = 10     # Full autonomous control
```

## Creating a New Agent

### 1. Define Input/Output Schemas

```python
from pydantic import BaseModel, Field

class MyAgentInput(BaseModel):
    """Input schema for my agent"""
    query: str = Field(..., description="User query")
    max_results: int = Field(default=10, ge=1, le=100)

class MyAgentOutput(BaseModel):
    """Output schema for my agent"""
    results: List[Dict[str, Any]]
    count: int
```

### 2. Implement Agent Class

```python
from app.core.agents.base import AgentBase, AuthorityLevel, AgentContext, AgentResult

class MyAgent(AgentBase):
    @property
    def name(self) -> str:
        return "my-agent"

    @property
    def role(self) -> str:
        return "Performs specific task X"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MyAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MyAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def default_tools(self) -> List[str]:
        return ["file_read", "text_search"]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        # Implement agent logic here

        # Log important steps
        self.logger.info("Processing query", extra={"query": input_data["query"]})

        # Use tools if needed
        if self.can_use_tool("file_read"):
            # Use file_read tool
            pass

        # Access memory if enabled
        if self.can_access_memory():
            # Access memory system
            pass

        # Return result
        return self.create_result(
            success=True,
            result_data={"results": [], "count": 0},
            output_text="Task completed successfully"
        )
```

### 3. Use the Agent

```python
from uuid import uuid4

# Configure agent
config = AgentConfig(
    workspace_id=uuid4(),
    authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION,
    allowed_tools=["file_read", "text_search", "code_executor"],
    enable_memory=True,
    model="claude-3-5-sonnet-20241022",
)

# Create agent instance
agent = MyAgent(config)

# Prepare context
context = AgentContext(
    workspace_id=workspace_id,
    user_id=user_id,
    session_id=session_id,
    memory_context=[...],
)

# Execute
result = await agent.execute(
    input_data={"query": "search for files", "max_results": 5},
    context=context,
)

# Check result
if result.success:
    print(f"Success: {result.output_text}")
    print(f"Cost: ${result.cost_estimate:.6f}")
    print(f"Time: {result.execution_time_seconds:.2f}s")
```

## Agent Configuration

### AgentConfig Fields

- **agent_id**: Unique instance identifier (auto-generated)
- **workspace_id**: Associated workspace
- **user_id**: Owner user ID
- **session_id**: Current session ID
- **authority_level**: Maximum authority (0-10)
- **allowed_tools**: List of tool names agent can use
- **enable_memory**: Enable memory system access
- **enable_self_evolution**: Enable self-evolution triggers
- **max_iterations**: Maximum execution iterations (1-100)
- **timeout_seconds**: Execution timeout (1-3600)
- **model**: LLM model to use
- **temperature**: LLM temperature (0.0-2.0)
- **extra_config**: Additional agent-specific config

## Agent Context

Context provided during execution:

- **workspace_id**: Current workspace
- **user_id**: Current user
- **session_id**: Current session
- **task_id**: Current task
- **parent_agent_id**: Parent agent if spawned
- **memory_context**: Relevant memories
- **workspace_rules**: Active rules
- **operating_plan**: Current operating plan
- **previous_results**: Results from previous steps
- **metadata**: Additional context

## Agent Results

Standardized result structure:

```python
{
    "success": True,
    "agent_name": "my-agent",
    "agent_id": "uuid",
    "result_data": {...},
    "output_text": "Human-readable output",
    "tools_used": ["file_read", "text_search"],
    "iterations_used": 3,
    "tokens_used": {"input_tokens": 1500, "output_tokens": 800, "total_tokens": 2300},
    "cost_estimate": 0.012345,
    "execution_time_seconds": 4.56,
    "error_message": None,
    "requires_approval": False,
    "requires_human_input": False,
    "checkpoint_created": False,
    "next_actions": ["verify_results", "update_database"],
    "metadata": {...},
    "created_at": "2026-06-03T..."
}
```

## Error Handling

### Exception Hierarchy

- **AgentError**: Base exception
  - **AgentValidationError**: Input/output validation failed
  - **AgentExecutionError**: Execution failed
  - **AgentAuthorizationError**: Insufficient authority

### Example Error Handling

```python
try:
    result = await agent.execute(input_data, context)
except AgentAuthorizationError as e:
    print(f"Authorization error: {e.message}")
    print(f"Required level: {e.details['required_level']}")
except AgentValidationError as e:
    print(f"Validation error: {e.message}")
    print(f"Details: {e.details}")
except AgentExecutionError as e:
    print(f"Execution error: {e.message}")
```

## Best Practices

1. **Always validate I/O**: Define strict Pydantic schemas
2. **Use structured logging**: Log with extra context fields
3. **Handle errors gracefully**: Catch and wrap exceptions appropriately
4. **Respect authority levels**: Check before performing privileged actions
5. **Use tool validation**: Check `can_use_tool()` before using tools
6. **Create checkpoints**: Set checkpoint_created=True for long operations
7. **Document schemas**: Add clear descriptions to all fields
8. **Return structured data**: Use result_data for machine-readable results
9. **Provide human output**: Use output_text for human-readable summaries
10. **Track costs**: Log token usage and cost estimates

## Testing Agents

```python
import pytest
from app.core.agents import AgentConfig, AgentContext, AuthorityLevel

@pytest.mark.asyncio
async def test_my_agent():
    # Setup
    config = AgentConfig(authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS)
    agent = MyAgent(config)
    context = AgentContext()

    # Execute
    result = await agent.execute(
        input_data={"query": "test", "max_results": 5},
        context=context,
    )

    # Assert
    assert result.success
    assert result.agent_name == "my-agent"
    assert "results" in result.result_data
```

## Integration with JARV System

Agents integrate with:

- **Model Router**: Automatic LLM provider selection
- **Tool Registry**: Access to 100+ tools across 9 groups
- **Memory System**: pgvector-based semantic memory
- **Authority System**: Multi-level permission control
- **Approval System**: Richard Boundary Operator integration
- **Swarm System**: Parallel agent execution
- **Self-Evolution**: Agent capability improvement

## Next Steps

1. Create agent registry (TASK 4.2)
2. Implement Orchestrator Agent (TASK 4.3)
3. Implement task state machine (TASK 4.4)
4. Add agent execution logs (TASK 4.5)
5. Implement all 31 specialist agents (Phase 13)
