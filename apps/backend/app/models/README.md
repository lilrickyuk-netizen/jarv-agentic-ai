# JARV Database Models

Complete SQLAlchemy 2.0 models for the JARV Agentic AI System.

## Models Overview

### Base Models (`base.py`)
- **Base**: DeclarativeBase for all models
- **TimestampMixin**: Adds `created_at` and `updated_at` timestamps
- **UUIDMixin**: Adds UUID primary key

### Core Models

#### User (`user.py`)
User authentication and profile management.
- Authentication: username, email, password_hash
- Authorization: is_active, is_admin
- Security: failed_login_attempts, last_login_at
- Profile: full_name, avatar_url, bio, timezone
- **Relationships**: workspaces, sessions, approvals

#### Workspace (`workspace.py`)
Dynamic project workspaces with configuration.
- Basic: name, description, slug
- Owner: owner_id (FK to users)
- Status: is_active, is_template, is_archived
- Configuration: workspace_type, authority_level, config (JSON)
- Swarm: max_subagents, active_subagent_count
- Features: swarm_enabled, self_evolution_enabled, company_mode_enabled
- Company: company_name, company_mission, company_structure (JSON)
- Statistics: total_tasks, completed_tasks, total_tokens_used
- **Relationships**: owner, agents, tasks, sessions, company_roles

#### Agent (`agent.py`)
Agent instances with configuration and state.
- Basic: name, agent_type, description
- Workspace: workspace_id (FK)
- Hierarchy: is_subagent, parent_agent_id (self-referential FK)
- Configuration: config (JSON), system_prompt, model_provider, model_name
- Authority: authority_level, allowed_tools, blocked_tools (JSON arrays)
- State: current_state, last_active_at
- Statistics: total_executions, successful_executions, failed_executions, total_tokens_used
- Company: company_role_id (FK to company_roles)
- **Relationships**: workspace, parent_agent, subagents, sessions, memories, tool_uses, company_role

#### Task (`task.py`)
Task management with dependencies and execution tracking.
- Basic: title, description, task_type
- Workspace: workspace_id (FK)
- Assignment: assigned_agent_id (FK to agents)
- Status: status, priority
- Execution: started_at, completed_at, failed_at
- Results: result (JSON), error_message, execution_logs (JSON array)
- Metrics: execution_duration_seconds, tokens_used, retry_count
- Context: context (JSON), metadata (JSON)
- **Dependencies**: Many-to-many self-referential via `task_dependencies` table
- **Relationships**: workspace, assigned_agent, dependencies, dependent_tasks

### Memory System

#### Memory (`memory.py`)
Agent memory with vector embeddings for semantic search.
- Agent: agent_id (FK)
- Content: memory_type, content, summary
- **Vector**: embedding (1536 dimensions for pgvector)
- Importance: importance_score, access_count, last_accessed_at
- Context: session_id (FK), task_id (FK), context (JSON), metadata (JSON)
- Expiration: expires_at, is_permanent
- **Indexes**: IVFFlat index on embedding vector for cosine similarity search
- **Relationships**: agent, session, task

### Session Management

#### AgentSession (`session.py`)
Agent execution sessions with state and resume capability.
- Basic: session_name, session_type
- References: user_id, workspace_id, agent_id (FKs)
- Status: status, is_paused, is_resumed
- Timing: started_at, ended_at, paused_at, resumed_at
- State: current_step, execution_stack (JSON), variables (JSON)
- Messages: messages (JSON array), execution_logs (JSON array)
- Metrics: total_tokens_used, total_api_calls, total_tool_uses, duration_seconds
- Context: initial_prompt, result (JSON), error_message, metadata (JSON)
- **Relationships**: user, workspace, agent, checkpoints, approvals

#### CheckpointState (`session.py`)
Checkpoint states for resume functionality.
- Session: session_id (FK)
- Checkpoint: checkpoint_name, checkpoint_type, description
- State: execution_state (JSON), variables (JSON), message_history (JSON array)
- Metrics: tokens_used_at_checkpoint, api_calls_at_checkpoint
- Resume: was_resumed_from, resumed_count
- **Relationships**: session

### Authority & Approval

#### Approval (`approval.py`)
Approval requests for Richard Boundary Operator.
- User: user_id, session_id (FKs)
- Request: approval_type, action_description, action_details (JSON)
- Authority: authority_level_required
- Status: status
- Response: approved, approved_at, rejected_at, response_message
- Execution: executed, executed_at, execution_result (JSON), execution_error
- Timeout: expires_at, is_expired
- Metadata: metadata (JSON)
- **Relationships**: user, session

### Tool System

#### ToolUse (`tool.py`)
Tool usage tracking and execution history.
- Agent: agent_id, session_id (FKs)
- Tool: tool_name, tool_group, tool_version
- Execution: input_params (JSON), output_result (JSON)
- Status: status, success, error_message
- Timing: started_at, completed_at, duration_ms
- Authority: authority_level_used, required_approval, approval_id (FK)
- Metadata: metadata (JSON)
- **Relationships**: agent, session, approval

### Company Operating Layer

#### CompanyRole (`company.py`)
Company roles for autonomous company operating.
- Workspace: workspace_id (FK)
- Role: role_name, role_type, department, description
- Hierarchy: parent_role_id (self-referential FK), level
- Responsibilities: responsibilities (JSON array), kpis (JSON), authority_level
- Configuration: config (JSON), skills_required (JSON array)
- Status: is_active, is_automated
- Statistics: total_agents, tasks_completed
- **Relationships**: workspace, parent_role, child_roles, agents

## Database Features

### Timestamps
All models include `created_at` and `updated_at` timestamps via `TimestampMixin`.

### UUID Primary Keys
All models use UUID primary keys via `UUIDMixin` for distributed system compatibility.

### JSON Fields
Extensive use of JSON fields for flexible configuration and metadata storage.

### Vector Embeddings
Memory model includes pgvector support for semantic similarity search with IVFFlat indexing.

### Relationships
Comprehensive relationship mapping with proper cascades:
- `CASCADE` for ownership relationships (delete children when parent deleted)
- `SET NULL` for optional references (preserve children when parent deleted)

### Indexes
Strategic indexes on:
- Foreign keys (automatic)
- Commonly queried fields (status, type, timestamps)
- Vector embeddings (IVFFlat for similarity search)

## Model Counts
- **Total Models**: 11
- **Base Models**: 3 (Base, TimestampMixin, UUIDMixin)
- **Domain Models**: 8 (User, Workspace, Agent, Task, Memory, AgentSession, Approval, ToolUse, CompanyRole)
- **Supporting Models**: 1 (CheckpointState)
- **Association Tables**: 1 (task_dependencies)

## Total Fields
Approximately 200+ fields across all models.

## Next Steps
1. Create Alembic migration for all models
2. Apply migration to create database schema
3. Test model relationships and constraints
4. Create seed data for development
