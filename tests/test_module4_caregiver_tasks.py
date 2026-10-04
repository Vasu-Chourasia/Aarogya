"""Tests for Module 4: Caregiver Task Creation and Orchestration."""

from aarogya.workflows.caregiver_task import CaregiverTaskWorkflow
from aarogya.models.enums import TaskStatus, ApprovalStatus


def test_task_proposal_requires_approval(brain, connector_registry, policy_engine, approval_manager, task_backend):
    workflow = CaregiverTaskWorkflow(
        brain=brain,
        connector_registry=connector_registry,
        policy_engine=policy_engine,
        approval_manager=approval_manager,
        task_backend=task_backend,
    )

    success, msg, data = workflow.propose_task(
        request_id="req_task_01",
        user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        task_description="Refill Medicine X 30 tablets",
        assigned_caregiver="usr_amit_01",
    )

    assert success is True
    assert data is not None
    assert "approval_id" in data
    assert data["status"] == "awaiting_approval"

    # Ensure task is not executed without approval
    approval_id = data["approval_id"]
    approval = approval_manager.get_approval(approval_id)
    assert approval.approval_status == ApprovalStatus.PENDING


def test_task_execution_after_approval(brain, connector_registry, policy_engine, approval_manager, task_backend):
    workflow = CaregiverTaskWorkflow(
        brain=brain,
        connector_registry=connector_registry,
        policy_engine=policy_engine,
        approval_manager=approval_manager,
        task_backend=task_backend,
    )

    # 1. Propose
    _, _, data = workflow.propose_task(
        request_id="req_task_02",
        user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        task_description="Refill Medicine X 30 tablets",
        assigned_caregiver="usr_amit_01",
    )
    approval_id = data["approval_id"]

    # 2. Approve
    ok, grant_msg, _ = approval_manager.grant_approval(approval_id, user_identity="usr_amit_01")
    assert ok is True

    # 3. Execute task creation
    exec_ok, exec_msg, task = workflow.execute_approved_task_creation(
        approval_id=approval_id,
        user_id="usr_amit_01",
    )

    assert exec_ok is True
    assert task is not None
    assert task.current_status == TaskStatus.APPROVED
    assert task.is_simulation is True
    assert task.backend_type == "local_development_task_backend"
