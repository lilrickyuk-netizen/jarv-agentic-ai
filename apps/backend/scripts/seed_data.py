#!/usr/bin/env python
"""
JARV Backend - Database Seed Data

Creates optional, editable seed/demo data for development and testing.
All seed data is clearly labeled and can be modified or deleted by users.
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    User,
    Workspace,
    Agent,
    Task,
    CompanyRole,
    Tool,
)


async def create_seed_user(session: AsyncSession) -> User:
    """Create seed admin user if not exists"""
    # Check if user already exists
    result = await session.execute(
        select(User).where(User.username == "admin")
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        print(f"  [INFO]  Admin user already exists: {existing_user.username}")
        return existing_user

    # Create admin user
    import bcrypt
    password_bytes = "admin123".encode('utf-8')
    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')

    user = User(
        id=uuid4(),
        username="admin",
        email="admin@jarv.local",
        full_name="JARV Administrator",
        password_hash=password_hash,  # Change in production!
        is_active=True,
        is_admin=True,
        timezone="UTC",
        bio="Seed administrator account for JARV system",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(user)
    await session.flush()
    print(f"  [OK] Created admin user: {user.username} (password: admin123)")
    return user


async def create_seed_workspace(session: AsyncSession, owner: User) -> Workspace:
    """Create seed demo workspace"""
    # Check if workspace already exists
    result = await session.execute(
        select(Workspace).where(Workspace.slug == "demo-workspace")
    )
    existing_workspace = result.scalar_one_or_none()

    if existing_workspace:
        print(f"  [INFO]  Demo workspace already exists: {existing_workspace.name}")
        return existing_workspace

    workspace = Workspace(
        id=uuid4(),
        name="Demo Workspace",
        slug="demo-workspace",
        description="[SEED DATA] Demo workspace for exploring JARV capabilities. Feel free to edit or delete.",
        owner_id=owner.id,
        workspace_type="general",
        is_active=True,
        is_template=False,
        is_archived=False,
        authority_level=5,
        config={
            "seed_data": True,
            "demo_mode": True,
            "theme": "default",
            "notifications_enabled": True,
        },
        max_subagents=10,
        active_subagent_count=0,
        swarm_enabled=True,
        self_evolution_enabled=True,
        company_mode_enabled=True,
        company_name="Demo Company",
        company_mission="Exploring AI agent capabilities with JARV",
        company_structure={
            "industry": "Technology",
            "size": "startup",
        },
        total_tasks=0,
        completed_tasks=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(workspace)
    await session.flush()
    print(f"  [OK] Created demo workspace: {workspace.name}")
    return workspace


async def create_seed_company_role(session: AsyncSession, workspace: Workspace) -> CompanyRole:
    """Create seed company role"""
    # Check if role already exists
    result = await session.execute(
        select(CompanyRole).where(
            CompanyRole.workspace_id == workspace.id,
            CompanyRole.role_name == "CEO"
        )
    )
    existing_role = result.scalar_one_or_none()

    if existing_role:
        print(f"  [INFO]  CEO role already exists in workspace")
        return existing_role

    role = CompanyRole(
        id=uuid4(),
        workspace_id=workspace.id,
        role_name="CEO",
        role_type="executive",
        department="Executive",
        description="[SEED DATA] Chief Executive Officer - highest authority",
        level=10,
        responsibilities=[
            "Strategic decision making",
            "Resource allocation",
            "High-risk approvals",
        ],
        authority_level=10,
        config={
            "can_approve_spending": True,
            "max_spend_amount": 10000,
            "can_manage_users": True,
            "can_create_agents": True,
            "seed_data": True,
        },
        skills_required=[
            "leadership",
            "strategic planning",
            "decision making",
        ],
        is_active=True,
        is_automated=False,
        total_agents=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(role)
    await session.flush()
    print(f"  [OK] Created company role: {role.role_name}")
    return role


async def create_seed_agent(session: AsyncSession, workspace: Workspace, role: CompanyRole) -> Agent:
    """Create seed demo agent"""
    # Check if agent already exists
    result = await session.execute(
        select(Agent).where(
            Agent.workspace_id == workspace.id,
            Agent.name == "Demo Agent"
        )
    )
    existing_agent = result.scalar_one_or_none()

    if existing_agent:
        print(f"  [INFO]  Demo agent already exists in workspace")
        return existing_agent

    agent = Agent(
        id=uuid4(),
        workspace_id=workspace.id,
        name="Demo Agent",
        agent_type="general",
        description="[SEED DATA] Demo agent for exploring JARV capabilities",
        system_prompt="You are a helpful demo agent in the JARV system. You can help users understand how agents work by performing sample tasks and demonstrations.",
        company_role_id=role.id,
        authority_level=5,
        current_state="idle",
        is_active=True,
        is_subagent=False,
        model_provider="claude",
        model_name="claude-3-5-sonnet-20241022",
        allowed_tools=["read", "write", "search", "calculate"],
        blocked_tools=[],
        total_executions=0,
        successful_executions=0,
        failed_executions=0,
        total_tokens_used=0,
        config={
            "seed_data": True,
            "demo_mode": True,
            "auto_retry": True,
            "max_retries": 3,
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(agent)
    await session.flush()
    print(f"  [OK] Created demo agent: {agent.name}")
    return agent


async def create_seed_task(session: AsyncSession, workspace: Workspace, agent: Agent) -> Task:
    """Create seed demo task"""
    # Check if task already exists
    result = await session.execute(
        select(Task).where(
            Task.workspace_id == workspace.id,
            Task.title == "Demo Task: Welcome to JARV"
        )
    )
    existing_task = result.scalar_one_or_none()

    if existing_task:
        print(f"  [INFO]  Demo task already exists in workspace")
        return existing_task

    task = Task(
        id=uuid4(),
        workspace_id=workspace.id,
        assigned_agent_id=agent.id,
        title="Demo Task: Welcome to JARV",
        description="[SEED DATA] This is a sample task demonstrating the JARV task management system. Explore the JARV interface and understand how tasks work. Feel free to edit, complete, or delete this task.",
        task_type="example",
        status="pending",
        priority=5,
        tokens_used=0,
        retry_count=0,
        context={
            "seed_data": True,
            "demo_mode": True,
            "purpose": "User onboarding and system demonstration",
            "instructions": "Explore the JARV interface",
            "expected_output": "Understanding of JARV task system",
        },
        meta_data={
            "seed_data": True,
            "demo": True,
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(task)
    await session.flush()
    print(f"  [OK] Created demo task: {task.title}")
    return task


async def create_seed_tools(session: AsyncSession) -> list[Tool]:
    """Create seed tool registry entries"""
    tools_data = [
        {
            "tool_name": "text_search",
            "tool_group": "information",
            "tool_version": "1.0.0",
            "description": "[SEED DATA] Search and retrieve text information from documents and databases",
            "minimum_authority_level": 1,
            "requires_approval": False,
            "is_dangerous": False,
        },
        {
            "tool_name": "file_read",
            "tool_group": "filesystem",
            "tool_version": "1.0.0",
            "description": "[SEED DATA] Read contents of files from approved directories",
            "minimum_authority_level": 2,
            "requires_approval": False,
            "is_dangerous": False,
        },
        {
            "tool_name": "file_write",
            "tool_group": "filesystem",
            "tool_version": "1.0.0",
            "description": "[SEED DATA] Write or modify files in approved directories",
            "minimum_authority_level": 3,
            "requires_approval": True,
            "is_dangerous": False,
        },
    ]

    created_tools = []
    for tool_data in tools_data:
        # Check if tool already exists
        result = await session.execute(
            select(Tool).where(Tool.tool_name == tool_data["tool_name"])
        )
        existing_tool = result.scalar_one_or_none()

        if existing_tool:
            print(f"  [INFO]  Tool already exists: {existing_tool.tool_name}")
            created_tools.append(existing_tool)
            continue

        tool = Tool(
            id=uuid4(),
            tool_name=tool_data["tool_name"],
            tool_group=tool_data["tool_group"],
            tool_version=tool_data["tool_version"],
            description=tool_data["description"],
            config_schema={"type": "object", "properties": {}},
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            minimum_authority_level=tool_data["minimum_authority_level"],
            requires_approval=tool_data["requires_approval"],
            is_dangerous=tool_data["is_dangerous"],
            is_active=True,
            is_deprecated=False,
            total_uses=0,
            success_count=0,
            failure_count=0,
            tags=["seed_data", "demo"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(tool)
        await session.flush()
        created_tools.append(tool)
        print(f"  [OK] Created seed tool: {tool.tool_name}")

    return created_tools


async def seed_all() -> None:
    """Create all seed data"""
    print("=" * 60)
    print("JARV Backend - Creating Seed Data")
    print("=" * 60)
    print("\n[INFO]  All seed data is clearly labeled and can be edited or deleted")
    print("[INFO]  Seed data is for development and demonstration purposes\n")

    async with AsyncSessionLocal() as session:
        try:
            print("Creating seed data...")
            print()

            # Create entities in order
            user = await create_seed_user(session)
            workspace = await create_seed_workspace(session, user)
            role = await create_seed_company_role(session, workspace)
            agent = await create_seed_agent(session, workspace, role)
            task = await create_seed_task(session, workspace, agent)
            tools = await create_seed_tools(session)

            # Commit all changes
            await session.commit()

            print()
            print("=" * 60)
            print("[OK] Seed data created successfully!")
            print("=" * 60)
            print("\nCreated:")
            print(f"  - 1 admin user (username: admin, password: admin123)")
            print(f"  - 1 demo workspace ('{workspace.name}')")
            print(f"  - 1 company role ('{role.role_name}')")
            print(f"  - 1 demo agent ('{agent.name}')")
            print(f"  - 1 demo task")
            print(f"  - {len(tools)} seed tools")
            print()
            print("[WARNING]  IMPORTANT: Change the admin password after first login!")
            print("=" * 60)

        except Exception as e:
            await session.rollback()
            print(f"\n[ERROR] Error creating seed data: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_all())
