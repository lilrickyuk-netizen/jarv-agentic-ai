"""
Tests for workflow execution
"""
import pytest
from sqlalchemy.orm import Session
from uuid import uuid4

from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.task import Task


@pytest.mark.workflow
@pytest.mark.integration
def test_task_creation_workflow(db_session: Session, test_workspace: Workspace, test_agent: Agent):
    """Test end-to-end task creation workflow"""
    # Step 1: Create task
    task = Task(
        id=uuid4(),
        title="Workflow Test Task",
        description="Testing workflow",
        workspace_id=test_workspace.id,
        status="pending",
        priority="high",
    )
    db_session.add(task)
    db_session.commit()

    # Step 2: Assign to agent
    task.assigned_agent_id = test_agent.id
    task.status = "assigned"
    db_session.commit()

    # Step 3: Mark as in progress
    task.status = "in_progress"
    db_session.commit()

    # Step 4: Complete task
    task.status = "completed"
    db_session.commit()

    # Verify final state
    final_task = db_session.query(Task).filter(Task.id == task.id).first()
    assert final_task.status == "completed"
    assert final_task.assigned_agent_id == test_agent.id


@pytest.mark.workflow
@pytest.mark.integration
def test_agent_swarm_workflow(db_session: Session, test_workspace: Workspace):
    """Test agent swarm coordination workflow"""
    # Create primary agent
    primary_agent = Agent(
        id=uuid4(),
        name="Primary Agent",
        role="orchestrator",
        workspace_id=test_workspace.id,
        is_active=True,
        authority_level=7,
    )
    db_session.add(primary_agent)

    # Create sub-agents
    sub_agents = []
    for i in range(3):
        sub_agent = Agent(
            id=uuid4(),
            name=f"Sub-Agent {i}",
            role=f"worker_{i}",
            workspace_id=test_workspace.id,
            is_active=True,
            authority_level=3,
        )
        db_session.add(sub_agent)
        sub_agents.append(sub_agent)

    db_session.commit()

    # Create tasks for sub-agents
    for i, sub_agent in enumerate(sub_agents):
        task = Task(
            id=uuid4(),
            title=f"Swarm Task {i}",
            workspace_id=test_workspace.id,
            assigned_agent_id=sub_agent.id,
            status="pending",
        )
        db_session.add(task)

    db_session.commit()

    # Verify swarm setup
    swarm_agents = db_session.query(Agent).filter(
        Agent.workspace_id == test_workspace.id,
        Agent.is_active == True
    ).all()

    assert len(swarm_agents) >= 4  # Primary + 3 sub-agents


@pytest.mark.workflow
@pytest.mark.integration
def test_approval_workflow(db_session: Session, test_workspace: Workspace, test_agent: Agent):
    """Test approval workflow for high-authority tasks"""
    from app.models.approval import Approval

    # Create high-authority task
    task = Task(
        id=uuid4(),
        title="High Authority Task",
        workspace_id=test_workspace.id,
        assigned_agent_id=test_agent.id,
        status="pending",
        authority_required=8,  # Requires approval
    )
    db_session.add(task)
    db_session.commit()

    # Create approval request
    approval = Approval(
        id=uuid4(),
        task_id=task.id,
        agent_id=test_agent.id,
        requested_authority=8,
        status="pending",
        action_type="execute_task",
    )
    db_session.add(approval)
    db_session.commit()

    # Approve
    approval.status = "approved"
    approval.approved_by = "test_admin"
    db_session.commit()

    # Execute task
    task.status = "in_progress"
    db_session.commit()

    # Verify workflow
    final_approval = db_session.query(Approval).filter(Approval.id == approval.id).first()
    assert final_approval.status == "approved"


@pytest.mark.workflow
@pytest.mark.integration
def test_error_handling_workflow(db_session: Session, test_workspace: Workspace, test_agent: Agent):
    """Test error handling in workflow execution"""
    # Create task
    task = Task(
        id=uuid4(),
        title="Error Test Task",
        workspace_id=test_workspace.id,
        assigned_agent_id=test_agent.id,
        status="in_progress",
    )
    db_session.add(task)
    db_session.commit()

    # Simulate error
    task.status = "failed"
    task.error_message = "Simulated error for testing"
    db_session.commit()

    # Retry task
    task.status = "pending"
    task.retry_count = 1
    db_session.commit()

    # Verify error handling
    failed_task = db_session.query(Task).filter(Task.id == task.id).first()
    assert failed_task.retry_count == 1
    assert failed_task.error_message is not None


@pytest.mark.workflow
@pytest.mark.integration
def test_checkpoint_workflow(db_session: Session, test_workspace: Workspace, test_agent: Agent):
    """Test checkpoint and resume workflow"""
    from app.models.boundary import SafeCheckpoint

    # Create task
    task = Task(
        id=uuid4(),
        title="Checkpoint Task",
        workspace_id=test_workspace.id,
        assigned_agent_id=test_agent.id,
        status="in_progress",
    )
    db_session.add(task)
    db_session.commit()

    # Create checkpoint
    checkpoint = SafeCheckpoint(
        id=uuid4(),
        task_id=task.id,
        agent_id=test_agent.id,
        checkpoint_data={"progress": 50, "step": "analysis"},
        is_resumable=True,
    )
    db_session.add(checkpoint)
    db_session.commit()

    # Simulate interruption
    task.status = "paused"
    db_session.commit()

    # Resume from checkpoint
    task.status = "in_progress"
    db_session.commit()

    # Verify checkpoint exists
    saved_checkpoint = db_session.query(SafeCheckpoint).filter(
        SafeCheckpoint.task_id == task.id
    ).first()
    assert saved_checkpoint is not None
    assert saved_checkpoint.is_resumable is True


@pytest.mark.workflow
@pytest.mark.integration
def test_multi_agent_collaboration(db_session: Session, test_workspace: Workspace):
    """Test multiple agents collaborating on related tasks"""
    # Create agents with different specializations
    coder = Agent(
        id=uuid4(),
        name="Coder Agent",
        role="coding",
        workspace_id=test_workspace.id,
        is_active=True,
        capabilities=["code_generation", "debugging"],
    )
    tester = Agent(
        id=uuid4(),
        name="Tester Agent",
        role="testing",
        workspace_id=test_workspace.id,
        is_active=True,
        capabilities=["test_creation", "test_execution"],
    )
    db_session.add_all([coder, tester])
    db_session.commit()

    # Create related tasks
    code_task = Task(
        id=uuid4(),
        title="Write Code",
        workspace_id=test_workspace.id,
        assigned_agent_id=coder.id,
        status="completed",
    )
    test_task = Task(
        id=uuid4(),
        title="Test Code",
        workspace_id=test_workspace.id,
        assigned_agent_id=tester.id,
        status="pending",
        depends_on_task_id=code_task.id,
    )
    db_session.add_all([code_task, test_task])
    db_session.commit()

    # Verify collaboration setup
    assert test_task.depends_on_task_id == code_task.id
