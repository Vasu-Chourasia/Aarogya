"""Tests for Module 5: Human-in-the-Loop Approval Manager."""

from aarogya.workflows.approval_manager import ApprovalManager
from aarogya.models.enums import ActionType, ApprovalStatus


def test_approval_binding_rejects_tampered_parameters():
    mgr = ApprovalManager()
    initial_params = {"medicine": "Medicine X", "quantity": 30}
    record = mgr.request_approval(
        request_id="req_hitl_01",
        user_identity="usr_amit_01",
        action_type=ActionType.PLACE_MEDICINE_ORDER,
        parameters=initial_params,
    )

    # Attempt to grant with changed parameters (e.g. quantity changed from 30 to 300)
    tampered_params = {"medicine": "Medicine X", "quantity": 300}
    ok, msg, updated_record = mgr.grant_approval(
        approval_id=record.approval_id,
        user_identity="usr_amit_01",
        provided_parameters=tampered_params,
    )

    assert ok is False
    assert "Parameters changed materially" in msg
    assert updated_record.approval_status == ApprovalStatus.REVOKED


def test_unauthorized_user_cannot_grant_approval():
    mgr = ApprovalManager()
    record = mgr.request_approval(
        request_id="req_hitl_02",
        user_identity="usr_amit_01",
        action_type=ActionType.CREATE_CAREGIVER_TASK,
        parameters={"task": "Buy medicine"},
    )

    # Different user attempts to approve
    ok, msg, _ = mgr.grant_approval(record.approval_id, user_identity="usr_unknown_99")
    assert ok is False
    assert "not authorized" in msg.lower()
