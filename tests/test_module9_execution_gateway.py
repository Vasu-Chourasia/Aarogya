"""Module 9 Tests: Controlled Tool Invocation & Execution Gateway.

Validates policy gates, capability readiness, input validation contracts,
healthcare authorization, HITL approval binding, execution modes,
idempotency protection, audit sanitization, outcome verification, and safety boundaries.
"""

import os
import sys
import json
import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from aarogya.config import Settings, ExecutionMode
from aarogya.models.enums import (
    GatewayExecutionStatus,
    CapabilityPolicyDecision,
    VerificationStatus,
    ApprovalStatus,
    ActionType,
    AuditEventType,
    HealthcareDomain,
)
from aarogya.models.gateway import ExecutionRequest, ExecutionResult
from aarogya.models.approval import compute_parameter_hash
from aarogya.models.connector import NormalizedCapability
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.policy.authorization_engine import PolicyAuthorizationEngine
from aarogya.workflows.approval_manager import ApprovalManager
from aarogya.workflows.verification import OutcomeVerificationService
from aarogya.orchestrator.audit_logger import AuditLogger
from aarogya.orchestrator.execution_gateway import ExecutionGateway, HandlerRegistration
from aarogya.orchestrator.agent import AarogyaAgent
from aarogya.cli import handle_execution_status, handle_execution_demo


@pytest.fixture
def test_env(tmp_path):
    """Provide isolated environment with configured registry, brain, and gateway."""
    log_file = tmp_path / "test_gateway_audit.jsonl"
    settings = Settings(
        execution_mode=ExecutionMode.SIMULATION,
        audit_log_file=str(log_file),
        redact_sensitive_data=True,
        live_execution_enabled=False,
    )
    brain = FamilyHealthBrain(seed_fictional_data=True)
    registry = ConnectorRegistry(execution_mode=ExecutionMode.SIMULATION)

    # Seed normalized capabilities into synchronizer
    caps = [
        NormalizedCapability(
            capability_id="conn:apollo_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="apollo_pharmacy",
            display_name="Apollo Direct Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory", "reserve_stock", "create_order"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:task_manager",
            source_platform="agenticorg",
            tenant_connector_id="task_manager",
            display_name="Caregiver Task Engine",
            domain=HealthcareDomain.CAREGIVER_TASKS,
            supported_operations=["create_caregiver_task", "query_caregiver_task"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:shopify_retail",
            source_platform="agenticorg",
            tenant_connector_id="shopify_retail",
            display_name="Shopify Retail Store",
            domain=HealthcareDomain.UNKNOWN,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=False,  # Generic commerce!
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:unhealthy_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="unhealthy_pharmacy",
            display_name="Unhealthy Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=False,  # Unhealthy
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:unknown_health_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="unknown_health_pharmacy",
            display_name="Unknown Health Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=None,  # Unknown health
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:unauthorized_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="unauthorized_pharmacy",
            display_name="Unauthorized Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=False,  # Explicitly unauthorized
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:unknown_auth_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="unknown_auth_pharmacy",
            display_name="Unknown Auth Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=None,  # Unknown authorization
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
        NormalizedCapability(
            capability_id="conn:stale_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="stale_pharmacy",
            display_name="Stale Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=True,  # Stale metadata
        ),
        NormalizedCapability(
            capability_id="conn:unregistered_service",
            source_platform="agenticorg",
            tenant_connector_id="unregistered_service",
            display_name="Unregistered Service",
            domain=HealthcareDomain.CAREGIVER_TASKS,
            supported_operations=["create_caregiver_task"],
            registered=False,  # Unregistered
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
        ),
    ]
    registry.synchronizer.reconcile_capabilities(caps)

    policy_engine = PolicyAuthorizationEngine(brain=brain)
    approval_manager = ApprovalManager()
    verification_service = OutcomeVerificationService(execution_mode=ExecutionMode.SIMULATION)
    audit_logger = AuditLogger(log_file=str(log_file), redact_sensitive=True)

    gateway = ExecutionGateway(
        settings=settings,
        brain=brain,
        connector_registry=registry,
        policy_engine=policy_engine,
        approval_manager=approval_manager,
        verification_service=verification_service,
        audit_logger=audit_logger,
    )

    return {
        "settings": settings,
        "brain": brain,
        "registry": registry,
        "policy_engine": policy_engine,
        "approval_manager": approval_manager,
        "verification_service": verification_service,
        "audit_logger": audit_logger,
        "gateway": gateway,
        "log_file": str(log_file),
    }


# ------------------------------------------------------------------------------
# 1. Valid simulated invocation
# ------------------------------------------------------------------------------
def test_01_valid_simulated_invocation(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30, "pincode": "560001"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        execution_mode=ExecutionMode.SIMULATION,
        confidence_score=0.95,
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.SIMULATED
    assert res.handler_invoked is True
    assert res.is_simulated is True
    assert res.output["available"] is True
    assert "Metformin" in res.output["medicine_name"]


# ------------------------------------------------------------------------------
# 2. Unknown capability rejected
# ------------------------------------------------------------------------------
def test_02_unknown_capability_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:non_existent_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.error_category == "CAPABILITY_NOT_FOUND"
    assert res.handler_invoked is False


# ------------------------------------------------------------------------------
# 3. Stale capability rejected
# ------------------------------------------------------------------------------
def test_03_stale_capability_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:stale_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_STALE_METADATA
    assert res.handler_invoked is False


# ------------------------------------------------------------------------------
# 4. Unregistered capability rejected
# ------------------------------------------------------------------------------
def test_04_unregistered_capability_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:unregistered_service",
        requested_operation="create_caregiver_task",
        input_payload={"title": "Test", "patient_id": "pat_rajesh_01", "assigned_to": "usr_amit_01"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="caregiver_tasks",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_NOT_REGISTERED


# ------------------------------------------------------------------------------
# 5. Unknown authorization rejected
# ------------------------------------------------------------------------------
def test_05_unknown_authorization_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:unknown_auth_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNAUTHORIZED
    assert "authorization required" in res.error_message.lower()


# ------------------------------------------------------------------------------
# 6. Explicitly unauthorized capability rejected
# ------------------------------------------------------------------------------
def test_06_explicitly_unauthorized_capability_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:unauthorized_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNAUTHORIZED


# ------------------------------------------------------------------------------
# 7. Unknown health status rejected
# ------------------------------------------------------------------------------
def test_07_unknown_health_status_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:unknown_health_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNHEALTHY


# ------------------------------------------------------------------------------
# 8. Unhealthy connector rejected
# ------------------------------------------------------------------------------
def test_08_unhealthy_connector_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:unhealthy_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNHEALTHY


# ------------------------------------------------------------------------------
# 9. Unsupported operation rejected
# ------------------------------------------------------------------------------
def test_09_unsupported_operation_rejected(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="initiate_payment",  # apollo_pharmacy only supports inventory/order/reserve
        input_payload={"order_id": "ord_1", "patient_id": "pat_rajesh_01", "amount": 100.0},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNSUPPORTED_OPERATION


# ------------------------------------------------------------------------------
# 10. Generic commerce rejected for pharmacy operation
# ------------------------------------------------------------------------------
def test_10_generic_commerce_rejected_for_pharmacy(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:shopify_retail",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY
    assert ("does not match workflow" in res.error_message) or ("Direct Pharmacy API alignment" in res.error_message)


# ------------------------------------------------------------------------------
# 11. Missing healthcare authorization rejected
# ------------------------------------------------------------------------------
def test_11_missing_healthcare_authorization_rejected(test_env):
    gw = test_env["gateway"]
    # usr_stranger_99 is not in Rajesh Kumar's family circle!
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_stranger_99",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "HEALTHCARE_AUTHORIZATION_DENIED"
    assert "not in patient" in res.error_message


# ------------------------------------------------------------------------------
# 12. Wrong patient scope rejected
# ------------------------------------------------------------------------------
def test_12_wrong_patient_scope_rejected(test_env):
    gw = test_env["gateway"]
    # Non-existent patient record
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_non_existent",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "HEALTHCARE_AUTHORIZATION_DENIED"
    assert "not found" in res.error_message


# ------------------------------------------------------------------------------
# 13. Missing approval blocks consequential action
# ------------------------------------------------------------------------------
def test_13_missing_approval_blocks_consequential_action(test_env):
    gw = test_env["gateway"]
    # create_caregiver_task is consequential and requires approval
    req = ExecutionRequest(
        capability_id="conn:task_manager",
        requested_operation="create_caregiver_task",
        input_payload={
            "title": "Collect evening medications",
            "patient_id": "pat_rajesh_01",
            "assigned_to": "usr_amit_01",
        },
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="caregiver_tasks",
        approval_id=None,  # Intentionally omitted
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.PENDING_APPROVAL
    assert res.error_category == "APPROVAL_REQUIRED"
    assert res.handler_invoked is False


# ------------------------------------------------------------------------------
# 14. Approval for a different operation rejected
# ------------------------------------------------------------------------------
def test_14_approval_for_different_operation_rejected(test_env):
    gw = test_env["gateway"]
    approval_mgr = test_env["approval_manager"]

    # Request and grant approval for create_caregiver_task
    task_payload = {"title": "Help with insulin", "patient_id": "pat_rajesh_01", "assigned_to": "usr_amit_01"}
    app_rec = approval_mgr.request_approval(
        request_id="req_task_1",
        user_identity="usr_amit_01",
        action_type=ActionType.CREATE_CAREGIVER_TASK,
        parameters=task_payload,
    )
    approval_mgr.grant_approval(app_rec.approval_id, "usr_amit_01", task_payload)

    # Attempt to use this task approval to authorize a medicine reservation!
    reserve_payload = {
        "medicine_name": "Metformin 500mg",
        "quantity": 30,
        "patient_id": "pat_rajesh_01",
    }
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="reserve_stock",
        input_payload=reserve_payload,
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        approval_id=app_rec.approval_id,  # Mismatched action!
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "INVALID_APPROVAL"
    assert "does not authorize requested operation" in res.error_message


# ------------------------------------------------------------------------------
# 15. Expired approval rejected where expiration is supported
# ------------------------------------------------------------------------------
def test_15_expired_approval_rejected(test_env):
    gw = test_env["gateway"]
    approval_mgr = test_env["approval_manager"]

    payload = {"title": "Collect test reports", "patient_id": "pat_rajesh_01", "assigned_to": "usr_amit_01"}
    app_rec = approval_mgr.request_approval(
        request_id="req_task_2",
        user_identity="usr_amit_01",
        action_type=ActionType.CREATE_CAREGIVER_TASK,
        parameters=payload,
    )
    approval_mgr.grant_approval(app_rec.approval_id, "usr_amit_01", payload)

    # Fast-forward approval expiration into past
    app_rec.expiration = datetime.utcnow() - timedelta(minutes=5)

    req = ExecutionRequest(
        capability_id="conn:task_manager",
        requested_operation="create_caregiver_task",
        input_payload=payload,
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="caregiver_tasks",
        approval_id=app_rec.approval_id,
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "INVALID_APPROVAL"
    assert "expired" in res.error_message.lower()


# ------------------------------------------------------------------------------
# 16. Invalid input schema rejected
# ------------------------------------------------------------------------------
def test_16_invalid_input_schema_rejected(test_env):
    gw = test_env["gateway"]
    # Missing required 'quantity' field
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "INPUT_VALIDATION_ERROR"
    assert res.handler_invoked is False


# ------------------------------------------------------------------------------
# 17. Unexpected input fields rejected (extra = "forbid")
# ------------------------------------------------------------------------------
def test_17_unexpected_input_fields_rejected(test_env):
    gw = test_env["gateway"]
    # Contains unexpected extra field 'arbitrary_injection'
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={
            "medicine_name": "Metformin 500mg",
            "quantity": 30,
            "malicious_injected_field": "some_exploit_value",
        },
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "INPUT_VALIDATION_ERROR"
    assert "Extra inputs are not permitted" in res.error_message or "extra" in res.error_message.lower()


# ------------------------------------------------------------------------------
# 18. Shadow Mode does not invoke handlers
# ------------------------------------------------------------------------------
def test_18_shadow_mode_does_not_invoke_handlers(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        execution_mode=ExecutionMode.CONNECTED_READ_ONLY,  # Shadow mode!
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.READY
    assert res.handler_invoked is False
    assert res.output["shadow_mode"] is True
    assert "withheld by policy" in res.output["message"]


# ------------------------------------------------------------------------------
# 19. Simulation Mode invokes only synthetic handlers
# ------------------------------------------------------------------------------
def test_19_simulation_mode_invokes_only_synthetic_handlers(test_env):
    gw = test_env["gateway"]
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.SIMULATED
    assert res.is_simulated is True
    assert res.handler_invoked is True
    assert res.output["is_simulated"] is True


# ------------------------------------------------------------------------------
# 20. Live execution remains disabled by default
# ------------------------------------------------------------------------------
def test_20_live_execution_disabled_by_default(test_env):
    gw = test_env["gateway"]
    # Request live execution mode
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        execution_mode=ExecutionMode.AUTHORIZED_EXECUTION,
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.error_category == "LIVE_EXECUTION_DISABLED"
    assert res.handler_invoked is False


# ------------------------------------------------------------------------------
# 21. Arbitrary MCP invocation is rejected
# ------------------------------------------------------------------------------
def test_21_arbitrary_mcp_invocation_rejected(test_env):
    gw = test_env["gateway"]
    # Attempting to call an arbitrary un-allowlisted MCP method
    req = ExecutionRequest(
        capability_id="mcp:system_shell_exec",
        requested_operation="arbitrary_unauthorized_mcp_command",
        input_payload={"command": "cat /etc/passwd"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="general_inquiry",
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "OPERATION_NOT_ALLOWLISTED"


# ------------------------------------------------------------------------------
# 22. Duplicate idempotency key does not cause duplicate invocation
# ------------------------------------------------------------------------------
def test_22_duplicate_idempotency_key_prevents_duplicate_invocation(test_env):
    gw = test_env["gateway"]
    idemp_key = f"key_{uuid.uuid4().hex[:10]}"

    req1 = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        idempotency_key=idemp_key,
    )
    res1 = gw.execute(req1)
    assert res1.status == GatewayExecutionStatus.SIMULATED
    assert res1.idempotency_matched is False

    # Second invocation with same idempotency key
    req2 = req1.model_copy()
    res2 = gw.execute(req2)
    assert res2.status == GatewayExecutionStatus.SIMULATED
    assert res2.idempotency_matched is True
    assert res2.execution_id == res1.execution_id


# ------------------------------------------------------------------------------
# 23. Timeout or uncertain outcome is not marked as failure-confirmed
# ------------------------------------------------------------------------------
def test_23_timeout_or_uncertain_outcome_requires_verification(test_env):
    gw = test_env["gateway"]
    idemp_key = "timeout_test_key"

    # Register a handler that raises TimeoutError
    def timeout_fn(req):
        raise TimeoutError("Socket read timeout after 10.0s")

    gw.register_handler(
        capability_pattern="conn:apollo_pharmacy",
        operation="get_order_status",
        is_consequential=False,
        requires_approval=False,
        handler_fn=timeout_fn,
    )

    # Ensure capability has get_order_status in supported operations
    cap = gw.connector_registry.get_normalized_capability("conn:apollo_pharmacy")
    cap.supported_operations.append("get_order_status")

    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_order_status",
        input_payload={"order_id": "ord_101", "patient_id": "pat_rajesh_01"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        idempotency_key=idemp_key,
    )

    res1 = gw.execute(req)
    assert res1.status == GatewayExecutionStatus.TIMED_OUT
    assert res1.error_category == "HANDLER_TIMEOUT"
    assert res1.verification_status == VerificationStatus.PENDING_VERIFICATION

    # Retrying an uncertain outcome must return REQUIRES_VERIFICATION
    res2 = gw.execute(req)
    assert res2.status == GatewayExecutionStatus.REQUIRES_VERIFICATION
    assert res2.error_category == "IDEMPOTENCY_RETRY_REQUIRES_VERIFICATION"


# ------------------------------------------------------------------------------
# 24. Simulated result is never marked as real-world completion
# ------------------------------------------------------------------------------
def test_24_simulated_result_never_marked_real_world_completion(test_env):
    gw = test_env["gateway"]
    approval_mgr = test_env["approval_manager"]

    order_payload = {
        "medicine_name": "Metformin 500mg",
        "quantity": 30,
        "patient_id": "pat_rajesh_01",
        "delivery_address": "123 Indiranagar, Bangalore",
        "prescription_id": "rx_metformin_01",
    }

    app_rec = approval_mgr.request_approval(
        request_id="req_ord_1",
        user_identity="usr_amit_01",
        action_type=ActionType.PLACE_MEDICINE_ORDER,
        parameters=order_payload,
    )
    approval_mgr.grant_approval(app_rec.approval_id, "usr_amit_01", order_payload)

    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="create_order",
        input_payload=order_payload,
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        approval_id=app_rec.approval_id,
        execution_mode=ExecutionMode.SIMULATION,
    )

    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.SIMULATED
    # Physical medicine delivery can NEVER be marked VERIFIED upon mere API response!
    assert res.verification_status != VerificationStatus.VERIFIED
    assert res.verification_status == VerificationStatus.PENDING_VERIFICATION


# ------------------------------------------------------------------------------
# 25. Audit records are sanitized
# ------------------------------------------------------------------------------
def test_25_audit_records_are_sanitized(test_env):
    gw = test_env["gateway"]
    log_file = test_env["log_file"]

    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    gw.execute(req)

    assert os.path.exists(log_file)
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Passwords or tokens should never appear in audit trail
    assert "secret" not in content.lower()
    assert "token" not in content.lower() or "grantex_token" not in content


# ------------------------------------------------------------------------------
# 26. API secrets do not appear in logs
# ------------------------------------------------------------------------------
def test_26_api_secrets_do_not_appear_in_logs(test_env):
    gw = test_env["gateway"]
    log_file = test_env["log_file"]

    # Inject mock error with secret-like string
    def failing_fn(req):
        raise ValueError("Failed with apikey=top_secret_api_key_8888")

    gw.register_handler(
        capability_pattern="conn:apollo_pharmacy",
        operation="get_price",
        is_consequential=False,
        requires_approval=False,
        handler_fn=failing_fn,
    )
    cap = gw.connector_registry.get_normalized_capability("conn:apollo_pharmacy")
    cap.supported_operations.append("get_price")

    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_price",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    gw.execute(req)

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Secrets should not be exposed
    assert "top_secret_api_key_8888" not in content


# ------------------------------------------------------------------------------
# 27. Family Health Brain remains unchanged during pre-execution validation
# ------------------------------------------------------------------------------
def test_27_family_health_brain_unchanged_during_validation(test_env):
    brain = test_env["brain"]
    gw = test_env["gateway"]

    initial_patient_count = len(brain._patients)
    initial_timeline_count = len(brain._timeline_events)
    rajesh_before = brain.get_patient("pat_rajesh_01").model_dump_json()

    # Run execution with multiple requests
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    gw.execute(req)

    assert len(brain._patients) == initial_patient_count
    assert len(brain._timeline_events) == initial_timeline_count
    rajesh_after = brain.get_patient("pat_rajesh_01").model_dump_json()
    assert rajesh_before == rajesh_after


# ------------------------------------------------------------------------------
# 28. Outcome verification is invoked at the appropriate boundary
# ------------------------------------------------------------------------------
def test_28_outcome_verification_invoked(test_env):
    gw = test_env["gateway"]
    verif = test_env["verification_service"]

    initial_records_count = len(verif._records)

    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    gw.execute(req)

    assert len(verif._records) == initial_records_count + 1


# ------------------------------------------------------------------------------
# 29. CLI execution-status and execution-demo work smoothly
# ------------------------------------------------------------------------------
def test_29_cli_execution_commands_work(capsys):
    handle_execution_status()
    out = capsys.readouterr().out
    assert "Aarogya -- Controlled Tool Invocation & Execution Gateway Status" in out
    assert "Live Execution Enabled:   No" in out

    handle_execution_demo(simulated=True)
    demo_out = capsys.readouterr().out
    assert "Aarogya -- Execution Gateway Controlled Invocation Demo" in demo_out
    assert "Demo Scenario 1: Non-Consequential Medicine Inventory Check" in demo_out
    assert "Demo Scenario 2: Consequential Task Without Approval" in demo_out


# ------------------------------------------------------------------------------
# 30. AarogyaAgent LangGraph Integration & Gateway Boundary
# ------------------------------------------------------------------------------
def test_30_aarogya_agent_gateway_integration(test_env):
    settings = test_env["settings"]
    brain = test_env["brain"]
    registry = test_env["registry"]
    agent = AarogyaAgent(settings=settings, brain=brain, connector_registry=registry)

    assert hasattr(agent, "execution_gateway")
    assert agent.execution_gateway is not None
    assert agent.execution_gateway.registered_handlers_count >= 8

    # Ensure agent processes standard inquiry without disruption
    req = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
    )
    res = agent.execution_gateway.execute(req)
    assert res.status == GatewayExecutionStatus.SIMULATED
