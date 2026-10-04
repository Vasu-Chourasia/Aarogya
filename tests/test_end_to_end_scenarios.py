"""Automated Tests for All 9 Required Scenarios (Section 11)."""

import pytest
from aarogya.orchestrator.agent import AarogyaAgent
from aarogya.config import Settings, ExecutionMode
from aarogya.models.request import HealthcareRequest
from aarogya.models.enums import (
    ExecutionStatus,
    MedicineAvailabilityOutcome,
    VerificationStatus,
    TaskStatus,
)
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.connectors.pharmacy_connector import MockDirectPharmacyConnector


# ==============================================================================
# Test 1: Missing Medicine Details
# User asks to check medicine availability without specifying the medicine.
# Expected:
#   * Agent requests missing information.
#   * No external tool is invoked.
# ==============================================================================
def test_scenario_1_missing_medicine_details(simulation_agent):
    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check whether my father's prescribed medicine is available.",
        patient_name="Rajesh Kumar",
    )
    resp = simulation_agent.process_request(req)

    assert resp["status"] == ExecutionStatus.BLOCKED_MISSING_INFORMATION.value
    assert "missing_information" in resp
    fields = [m["field"] for m in resp["missing_information"]]
    assert "medicine_name" in fields
    assert "claim_safeguard" not in resp or "No medicine availability" in resp.get("claim_safeguard", "")


# ==============================================================================
# Test 2: Pharmacy Connector Missing
# User provides:
#   Patient: Rajesh Kumar
#   Medicine: Medicine X
#   Quantity: 30
# Expected:
#   * Connector capability check identifies the missing integration.
#   * No availability claim is generated.
#   * No order is created.
#   * No caregiver task is created.
# ==============================================================================
def test_scenario_2_pharmacy_connector_missing(brain):
    # Non-simulation mode without configured pharmacy integration
    settings = Settings(execution_mode=ExecutionMode.AUTHORIZED_EXECUTION)
    registry = ConnectorRegistry(execution_mode=ExecutionMode.AUTHORIZED_EXECUTION)
    
    agent = AarogyaAgent(
        settings=settings,
        brain=brain,
        connector_registry=registry,
        pharmacy_connector=None,  # No connector attached
    )

    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check if Medicine X 30 tablets is available for Rajesh Kumar.",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        quantity=30,
    )
    resp = agent.process_request(req)

    assert resp["status"] == ExecutionStatus.BLOCKED_CONNECTOR_MISSING.value
    assert "No configured pharmacy integration" in resp["blocker_reason"]
    assert "missing_requirements" in resp
    assert "availability" not in resp  # No availability claim
    assert "order" not in resp         # No order created


# ==============================================================================
# Test 3: Pharmacy Returns Available
# Mock pharmacy returns a valid availability response.
# Expected:
#   * Availability is reported with its source.
#   * No order is placed automatically.
#   * No task is created without approval.
# ==============================================================================
def test_scenario_3_pharmacy_returns_available(brain, connector_registry, task_backend):
    mock_pharmacy = MockDirectPharmacyConnector(simulated_inventory={"medicine x": 100})
    settings = Settings(execution_mode=ExecutionMode.SIMULATION)
    agent = AarogyaAgent(
        settings=settings,
        brain=brain,
        connector_registry=connector_registry,
        pharmacy_connector=mock_pharmacy,
        task_backend=task_backend,
    )

    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check if Medicine X 30 tablets is available for Rajesh Kumar.",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        quantity=30,
    )
    resp = agent.process_request(req)

    assert resp["status"] == ExecutionStatus.EXECUTED.value
    assert "availability" in resp
    assert resp["availability"]["outcome"] == MedicineAvailabilityOutcome.AVAILABLE.value
    assert resp["availability"]["available_quantity"] == 100
    assert "simulated_direct_pharmacy_api" in resp["availability"]["source"]
    assert "Order placement requires explicit authorization" in resp["recommendation"]
    assert len(task_backend.list_tasks_for_patient("pat_rajesh_01")) == 0  # No task auto-created


# ==============================================================================
# Test 4: Pharmacy Returns Unavailable
# Expected:
#   * Medicine is reported unavailable according to the provider response.
#   * Agent explains the result.
#   * A caregiver task may be proposed.
#   * No task is created without explicit approval.
# ==============================================================================
def test_scenario_4_pharmacy_returns_unavailable(brain, connector_registry, task_backend):
    mock_pharmacy = MockDirectPharmacyConnector(simulated_inventory={"medicine x": 0})
    settings = Settings(execution_mode=ExecutionMode.SIMULATION)
    agent = AarogyaAgent(
        settings=settings,
        brain=brain,
        connector_registry=connector_registry,
        pharmacy_connector=mock_pharmacy,
        task_backend=task_backend,
    )

    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check if Medicine X 30 tablets is available for Rajesh Kumar.",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        quantity=30,
    )
    resp = agent.process_request(req)

    assert resp["status"] == ExecutionStatus.EXECUTED.value
    assert resp["availability"]["outcome"] == MedicineAvailabilityOutcome.UNAVAILABLE.value
    assert "out of stock" in resp["availability"]["details"].lower()
    assert "caregiver task" in resp["recommendation"].lower()
    # Explicit check: No task has been created automatically
    assert len(task_backend.list_tasks_for_patient("pat_rajesh_01")) == 0


# ==============================================================================
# Test 5: User Approves Caregiver Task
# Expected:
#   * Approval is associated with the exact task.
#   * Task creation is attempted only if a real task backend or explicitly labeled simulation exists.
#   * Task ID or actual creation failure is reported.
#   * No medicine order or payment occurs.
# ==============================================================================
def test_scenario_5_user_approves_caregiver_task(brain, connector_registry, task_backend):
    settings = Settings(execution_mode=ExecutionMode.SIMULATION)
    agent = AarogyaAgent(
        settings=settings,
        brain=brain,
        connector_registry=connector_registry,
        task_backend=task_backend,
    )

    # 1. Propose task
    ok, msg, data = agent.task_workflow.propose_task(
        request_id="req_task_refill_01",
        user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        task_description="Refill Medicine X 30 tablets",
        assigned_caregiver="usr_amit_01",
        medicine_reference="Medicine X",
        required_quantity=30,
    )
    assert ok is True
    approval_id = data["approval_id"]

    # 2. Grant approval
    grant_ok, _, _ = agent.approval_manager.grant_approval(
        approval_id=approval_id,
        user_identity="usr_amit_01",
    )
    assert grant_ok is True

    # 3. Execute approved task creation
    exec_ok, exec_msg, task = agent.task_workflow.execute_approved_task_creation(
        approval_id=approval_id,
        user_id="usr_amit_01",
    )
    assert exec_ok is True
    assert task is not None
    assert task.task_id.startswith("tsk_local_")
    assert task.is_simulation is True
    assert task.backend_type == "local_development_task_backend"
    assert task.current_status == TaskStatus.APPROVED


# ==============================================================================
# Test 6: Connector Timeout
# Expected:
#   * Status is PROVIDER_ERROR or UNKNOWN.
#   * Agent does not claim medicine is unavailable.
# ==============================================================================
def test_scenario_6_connector_timeout(brain, connector_registry):
    mock_pharmacy_timeout = MockDirectPharmacyConnector(simulate_timeout=True)
    settings = Settings(execution_mode=ExecutionMode.SIMULATION)
    agent = AarogyaAgent(
        settings=settings,
        brain=brain,
        connector_registry=connector_registry,
        pharmacy_connector=mock_pharmacy_timeout,
    )

    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check if Medicine X 30 tablets is available for Rajesh Kumar.",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        quantity=30,
    )
    resp = agent.process_request(req)

    assert resp["availability"]["outcome"] == MedicineAvailabilityOutcome.PROVIDER_ERROR.value
    assert resp["availability"]["outcome"] != MedicineAvailabilityOutcome.UNAVAILABLE.value
    assert "provider communication error, not confirmed medicine unavailability" in resp["availability"]["details"].lower()


# ==============================================================================
# Test 7: Unauthorized Request
# Expected:
#   * Operation is blocked.
#   * No sensitive information is disclosed.
#   * No external write operation is performed.
# ==============================================================================
def test_scenario_7_unauthorized_request(simulation_agent):
    req = HealthcareRequest(
        user_id="usr_stranger_99",  # Not in Rajesh Kumar's family circle
        raw_text="Check if Medicine X 30 tablets is available for Rajesh Kumar.",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        quantity=30,
    )
    resp = simulation_agent.process_request(req)

    assert resp["status"] == ExecutionStatus.BLOCKED_UNAUTHORIZED.value
    assert "not authorized" in resp["blocker_reason"].lower()
    assert "availability" not in resp
    assert "prescriptions" not in resp


# ==============================================================================
# Test 8: Duplicate Request (Idempotency)
# Expected:
#   * Idempotency safeguards prevent unintended duplicate task creation or ordering.
# ==============================================================================
def test_scenario_8_duplicate_request_idempotency(brain, connector_registry, task_backend):
    settings = Settings(execution_mode=ExecutionMode.SIMULATION)
    agent = AarogyaAgent(settings=settings, brain=brain, connector_registry=connector_registry, task_backend=task_backend)

    # Propose and approve first task
    _, _, data = agent.task_workflow.propose_task(
        request_id="req_dup_01",
        user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        task_description="Refill Medicine X 30 tablets",
        assigned_caregiver="usr_amit_01",
    )
    approval_id = data["approval_id"]
    agent.approval_manager.grant_approval(approval_id, "usr_amit_01")

    # Execute task with idempotency key
    idempotency_key = "idemp_refill_2026_01"
    _, _, task1 = agent.task_workflow.execute_approved_task_creation(
        approval_id=approval_id,
        user_id="usr_amit_01",
        idempotency_key=idempotency_key,
    )

    # Attempt duplicate execution with same idempotency key
    _, _, task2 = agent.task_workflow.execute_approved_task_creation(
        approval_id=approval_id,
        user_id="usr_amit_01",
        idempotency_key=idempotency_key,
    )

    assert task1.task_id == task2.task_id
    assert len(task_backend.list_tasks_for_patient("pat_rajesh_01")) == 1


# ==============================================================================
# Test 9: Unverified Completion
# Expected:
#   * Agent does not claim the medicine was obtained or delivered without appropriate evidence.
# ==============================================================================
def test_scenario_9_unverified_completion(verification_service):
    # Simulated order creation
    exec_rec = verification_service.create_execution_record(
        request_id="req_order_100",
        operation_type="medicine_order",
        status="executing",
    )

    # API response says "accepted"
    verification_service.record_execution_success(
        operation_id=exec_rec.operation_id,
        provider_response={"order_id": "ord_pharma_99", "status": "order_accepted"},
        evidence_description="Order accepted by pharmacy API",
        evidence_source="pharmacy_api",
        is_delivery_or_clinical=True,
    )

    record = verification_service.get_record(exec_rec.operation_id)
    # The order was accepted by API, but delivery is NOT claimed to be completed
    assert record.status == "executed"
    assert record.verification_status == VerificationStatus.PENDING_VERIFICATION
    assert record.verification_status != VerificationStatus.VERIFIED

    # Check that without physical proof (POD/OTP), it cannot be verified
    verification_service.verify_delivery_outcome(
        operation_id=exec_rec.operation_id,
        evidence_type="proof_of_delivery",
        proof_payload={"pod_signature": None, "verified_otp": None},
    )
    unverified_record = verification_service.get_record(exec_rec.operation_id)
    assert unverified_record.verification_status == VerificationStatus.UNVERIFIED
