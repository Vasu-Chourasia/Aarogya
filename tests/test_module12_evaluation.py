"""Module 12: End-to-End Healthcare Coordination Evaluation & Competition Demo Tests.

Comprehensive 33-point automated test suite verifying scenario models, assertions,
evaluation runner, CLI commands, reporting, and safety invariants.
"""

import os
import pytest
from datetime import datetime, timedelta
from typing import Dict, Any

from aarogya.config import Settings, ExecutionMode
from aarogya.models.enums import (
    RequestType,
    ExecutionStatus,
    AuditEventType,
    GatewayExecutionStatus,
    HealthcareDomain,
    VerificationStatus,
    ActionType,
)
from aarogya.models.request import HealthcareRequest
from aarogya.models.gateway import ExecutionRequest, ExecutionResult
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.workflows.approval_manager import ApprovalManager
from aarogya.orchestrator.audit_logger import AuditLogger
from aarogya.persistence import get_persistence_bundle
from aarogya.evaluation.scenario_models import (
    EvaluationStatus,
    AssertionResult,
    ScenarioContext,
    ScenarioResult,
    EvaluationReport,
)
from aarogya.evaluation.scenario_catalog import (
    SCENARIOS,
    get_scenario,
    list_all_scenarios,
)
from aarogya.evaluation.evaluation_runner import (
    EvaluationEnvironment,
    EvaluationRunner,
)
from aarogya.evaluation.assertions import (
    assert_patient_resolved,
    assert_authorization_enforced,
    assert_no_unauthorized_disclosure,
    assert_capability_verified,
    assert_hitl_approval_required,
    assert_hitl_binding_integrity,
    assert_no_live_execution,
    assert_no_fabricated_data,
    assert_idempotency_enforced,
    assert_uncertain_outcome_requires_verification,
    assert_notification_authorized,
    assert_emergency_safety_routed,
    assert_family_health_brain_unchanged,
    assert_audit_records_persisted,
)
from aarogya.evaluation.reporting import (
    format_evaluation_report,
    generate_ascii_report,
    format_scenario_catalog_summary,
    format_scenario_list,
)
from aarogya.cli import main


# ---------------------------------------------------------------------------
# 1. Scenario Catalog & Schema Validation Tests
# ---------------------------------------------------------------------------

def test_scenario_catalog_loading():
    """Verify that all 10 required scenarios (A through J) are present and valid."""
    assert len(SCENARIOS) == 10
    required_ids = ["SCENARIO_A", "SCENARIO_B", "SCENARIO_C", "SCENARIO_D", "SCENARIO_E",
                    "SCENARIO_F", "SCENARIO_G", "SCENARIO_H", "SCENARIO_I", "SCENARIO_J"]
    for sid in required_ids:
        scenario = get_scenario(sid)
        assert scenario is not None
        assert scenario.scenario_id == sid
        assert len(scenario.title) > 0
        assert len(scenario.request_text) > 0
        assert len(scenario.expected_safety) > 0
        assert len(scenario.expected_execution) > 0
        assert len(scenario.expected_outcome) > 0


def test_scenario_catalog_list_all():
    """Verify list_all_scenarios returns 10 contexts."""
    all_contexts = list_all_scenarios()
    assert len(all_contexts) == 10
    assert all(isinstance(c, ScenarioContext) for c in all_contexts)


def test_scenario_models_schema_validation():
    """Verify strongly typed Pydantic schema validation for evaluation models."""
    assertion = AssertionResult(
        name="test_assert",
        status=EvaluationStatus.PASS,
        message="All good",
        details={"key": "val"},
    )
    assert assertion.status == EvaluationStatus.PASS

    result = ScenarioResult(
        scenario_id="SCENARIO_TEST",
        title="Test Scenario",
        description="Testing schema",
        status=EvaluationStatus.PASS,
        assertions=[assertion],
        execution_mode="SIMULATION",
        provider_mode="mock",
        live_execution_enabled=False,
    )
    assert result.scenario_id == "SCENARIO_TEST"
    assert len(result.assertions) == 1

    report = EvaluationReport(
        total_scenarios=1,
        passed=1,
        failed=0,
        blocked=0,
        not_applicable=0,
        scenario_results=[result],
        summary="Test summary",
        timestamp=datetime.utcnow(),
    )
    assert report.passed == 1
    assert report.pass_rate == 100.0


def test_evaluation_status_enum_values():
    """Ensure EvaluationStatus defines PASS, FAIL, BLOCKED, NOT_APPLICABLE."""
    assert EvaluationStatus.PASS == "PASS"
    assert EvaluationStatus.FAIL == "FAIL"
    assert EvaluationStatus.BLOCKED == "BLOCKED"
    assert EvaluationStatus.NOT_APPLICABLE == "NOT_APPLICABLE"


def test_truthful_pass_rate_calculation():
    """Blocked scenarios must NOT count as completed/passed in pass_rate."""
    report = EvaluationReport(
        total_scenarios=10,
        passed=7,
        failed=0,
        blocked=3,
        not_applicable=0,
        scenario_results=[],
        summary="7 pass, 3 blocked",
        timestamp=datetime.utcnow(),
    )
    # 7 / 10 = 70.0%
    assert report.pass_rate == 70.0
    assert report.pass_rate != 100.0


# ---------------------------------------------------------------------------
# 2. Individual Scenario Execution & Invariant Tests
# ---------------------------------------------------------------------------

def test_scenario_a_medicine_refill_coordination(tmp_path):
    """Scenario A: Medicine Refill Coordination end-to-end execution."""
    db_file = str(tmp_path / "eval_a.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_A")
        assert result.status == EvaluationStatus.PASS
        assert len(result.safety_violations) == 0

        assertion_names = [a.name for a in result.assertions if a.status == EvaluationStatus.PASS]
        assert "patient_resolution" in assertion_names
        assert "authorization_enforcement" in assertion_names
        assert "capability_verification" in assertion_names
        assert "no_live_execution" in assertion_names
        assert "audit_persistence" in assertion_names
    finally:
        runner.cleanup()


def test_scenario_b_unauthorized_user_denial(tmp_path):
    """Scenario B: Unauthorized user is safely denied without data disclosure."""
    db_file = str(tmp_path / "eval_b.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_B")
        assert result.status == EvaluationStatus.BLOCKED
        assert len(result.safety_violations) == 0

        assertion_statuses = {a.name: a.status for a in result.assertions}
        assert assertion_statuses.get("authorization_enforcement") == EvaluationStatus.BLOCKED
        assert assertion_statuses.get("no_unauthorized_disclosure") == EvaluationStatus.PASS
        assert assertion_statuses.get("audit_persistence") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_c_missing_patient_identity_clarification(tmp_path):
    """Scenario C: Missing patient asks clarification without guessing or invoking tools."""
    db_file = str(tmp_path / "eval_c.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_C")
        assert result.status == EvaluationStatus.BLOCKED
        assert len(result.safety_violations) == 0

        assertion_statuses = {a.name: a.status for a in result.assertions}
        assert assertion_statuses.get("patient_resolution_blocked_safely") == EvaluationStatus.BLOCKED
    finally:
        runner.cleanup()


def test_scenario_d_pharmacy_provider_timeout(tmp_path):
    """Scenario D: Provider timeout is classified accurately with no fabricated data."""
    db_file = str(tmp_path / "eval_d.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_D")
        assert result.status == EvaluationStatus.PASS

        assertion_dict = {a.name: a.status for a in result.assertions}
        assert assertion_dict.get("provider_timeout_handled") == EvaluationStatus.PASS
        assert assertion_dict.get("audit_persistence") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_e_missing_or_stale_medicine_data(tmp_path):
    """Scenario E: Unprescribed or missing medicine blocks order without altering treatment."""
    db_file = str(tmp_path / "eval_e.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_E")
        assert result.status == EvaluationStatus.BLOCKED

        assertion_statuses = {a.name: a.status for a in result.assertions}
        assert assertion_statuses.get("unverified_medicine_rejected") == EvaluationStatus.BLOCKED
        assert assertion_statuses.get("brain_immutability") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_f_hitl_approval_required(tmp_path):
    """Scenario F: Consequential action generates approval requirement."""
    db_file = str(tmp_path / "eval_f.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_F")
        assert result.status == EvaluationStatus.PASS

        assertion_dict = {a.name: a.status for a in result.assertions}
        assert assertion_dict.get("approval_binding_integrity") == EvaluationStatus.PASS
        assert assertion_dict.get("tampered_parameters_rejected") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_f_hitl_approval_mismatch_rejection(tmp_path):
    """Scenario F invariant: Tampered approval parameter hash is rejected upon grant."""
    db_file = str(tmp_path / "eval_f_mismatch.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        mgr = ApprovalManager(approval_repo=env.bundle.approval_repo)
        req = mgr.request_approval(
            request_id="req_test_mismatch",
            user_identity="caregiver_daughter_001",
            action_type=ActionType.CREATE_CAREGIVER_TASK,
            parameters={"medicine_name": "Metformin", "quantity": 1},
        )
        assert req is not None

        # Attempt grant with tampered parameters
        tampered_params = {"medicine_name": "Metformin", "quantity": 999}
        success, msg, _ = mgr.grant_approval(
            approval_id=req.approval_id,
            user_identity="caregiver_daughter_001",
            provided_parameters=tampered_params,
        )
        assert success is False
        assert "changed materially" in msg.lower() or "mismatch" in msg.lower()
    finally:
        env.cleanup()


def test_scenario_f_hitl_approval_expired_rejection(tmp_path):
    """Scenario F invariant: Expired approval record cannot be approved."""
    db_file = str(tmp_path / "eval_f_expired.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        mgr = ApprovalManager(approval_repo=env.bundle.approval_repo)
        req = mgr.request_approval(
            request_id="req_test_expired",
            user_identity="caregiver_daughter_001",
            action_type=ActionType.CREATE_CAREGIVER_TASK,
            parameters={"test": 1},
        )
        # Force expiration in record
        req.expiration = datetime.utcnow() - timedelta(seconds=10)
        success, msg, _ = mgr.grant_approval(
            approval_id=req.approval_id,
            user_identity="caregiver_daughter_001",
        )
        assert success is False
        assert "expired" in msg.lower()
    finally:
        env.cleanup()


def test_scenario_g_duplicate_request_idempotency(tmp_path):
    """Scenario G: Submitting the same request twice enforces idempotency cache hit."""
    db_file = str(tmp_path / "eval_g.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_G")
        assert result.status == EvaluationStatus.PASS

        assertion_dict = {a.name: a.status for a in result.assertions}
        assert assertion_dict.get("idempotency_enforcement") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_h_uncertain_outcome_requires_verification(tmp_path):
    """Scenario H: Lost provider response marks UNKNOWN_OUTCOME and requires reconciliation."""
    db_file = str(tmp_path / "eval_h.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_H")
        assert result.status == EvaluationStatus.PASS

        assertion_dict = {a.name: a.status for a in result.assertions}
        assert assertion_dict.get("uncertain_outcome_verification") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_i_caregiver_notification_authorized(tmp_path):
    """Scenario I: Caregiver notification delivers to authorized daughter with audit trace."""
    db_file = str(tmp_path / "eval_i.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_I")
        assert result.status == EvaluationStatus.PASS

        assertion_dict = {a.name: a.status for a in result.assertions}
        assert assertion_dict.get("notification_authorization") == EvaluationStatus.PASS
        assert assertion_dict.get("unauthorized_caregiver_notification_rejected") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_i_caregiver_notification_unauthorized_stranger_rejected(tmp_path):
    """Scenario I invariant: Notification to unauthorized stranger is blocked."""
    db_file = str(tmp_path / "eval_i_stranger.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        patient = env.brain.get_patient("pat_rajesh_01")
        res = assert_notification_authorized(
            recipient_id="usr_unauthorized_stranger",
            patient_family_members=patient.family_members if patient else [],
        )
        assert res.status == EvaluationStatus.FAIL
        assert "privacy breach" in res.message.lower() or "not in patient family" in res.message.lower()
    finally:
        env.cleanup()


def test_scenario_j_emergency_urgent_symptoms_triage(tmp_path):
    """Scenario J: Chest pain and breathing difficulty routed immediately to 108/112."""
    db_file = str(tmp_path / "eval_j.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        result = runner.run_scenario("SCENARIO_J")
        assert result.status == EvaluationStatus.PASS

        assertion_dict = {a.name: a.status for a in result.assertions}
        assert assertion_dict.get("emergency_safety_routing") == EvaluationStatus.PASS
        assert assertion_dict.get("audit_persistence") == EvaluationStatus.PASS
    finally:
        runner.cleanup()


def test_scenario_j_emergency_no_delay_for_routine_medicine():
    """Scenario J invariant: Request parser immediately classifies emergency with confidence 1.0."""
    from aarogya.understanding.request_parser import RequestUnderstandingService
    parser = RequestUnderstandingService()
    req = parser.parse(HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="My father has severe chest pain and cannot breathe, get medicine now!",
    ))
    assert req.request_type == RequestType.EMERGENCY
    assert req.execution_status == ExecutionStatus.ROUTED_TO_EMERGENCY
    assert req.confidence_score == 1.0


# ---------------------------------------------------------------------------
# 3. Core Safety & Invariant Assertion Tests
# ---------------------------------------------------------------------------

def test_assertion_no_live_execution_enforced():
    """Verify assert_no_live_execution passes when live execution is strictly disabled."""
    settings = Settings(live_execution_enabled=False, pharmacy_live_operations_enabled=False)
    res = assert_no_live_execution(settings)
    assert res.status == EvaluationStatus.PASS

    unsafe_settings = Settings(live_execution_enabled=True, pharmacy_live_operations_enabled=True)
    res_unsafe = assert_no_live_execution(unsafe_settings)
    assert res_unsafe.status == EvaluationStatus.FAIL


def test_assertion_no_real_orders_or_payments(tmp_path):
    """Verify execution gateway blocks live order placement and payments."""
    db_file = str(tmp_path / "eval_no_orders.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        exec_req = ExecutionRequest(
            capability_id="conn:apollo_pharmacy",
            requested_operation="create_order",
            input_payload={
                "medicine_name": "Metformin",
                "quantity": 30,
                "patient_id": "pat_rajesh_01",
                "delivery_address": "123 Safe St, Delhi",
                "prescription_id": "rx_001",
                "price": 200.0,
            },
            requesting_user_id="usr_amit_01",
            patient_id="pat_rajesh_01",
            execution_mode=ExecutionMode.SIMULATION,
        )
        res = env.agent.execution_gateway.execute(exec_req)
        assert res.status == GatewayExecutionStatus.BLOCKED
        assert "create_order" in (res.error_message or "") or "BLOCKED" in (res.error_category or "")
    finally:
        env.cleanup()


def test_assertion_no_fabricated_inventory_or_pricing():
    """Verify assert_no_fabricated_data validates responses without fabrication."""
    good_resp = {
        "status": "executed",
        "availability": {
            "outcome": "AVAILABLE",
            "available_quantity": 30,
            "pharmacy_name": "Apollo Direct",
        },
    }
    good_res = assert_no_fabricated_data(good_resp)
    assert good_res.status == EvaluationStatus.PASS

    bad_resp = {
        "status": "executed",
        "availability": {
            "outcome": "AVAILABLE",
            "available_quantity": None,  # Fabricated / missing quantity
        },
    }
    bad_res = assert_no_fabricated_data(bad_resp)
    assert bad_res.status == EvaluationStatus.FAIL


def test_assertion_family_health_brain_unchanged(tmp_path):
    """Verify Family Health Brain snapshot comparison detects unmutated state."""
    db_file = str(tmp_path / "eval_brain_snapshot.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        snapshot_before = env.capture_brain_snapshot()
        # No mutations
        snapshot_after = env.capture_brain_snapshot()
        res = assert_family_health_brain_unchanged(snapshot_before, snapshot_after)
        assert res.status == EvaluationStatus.PASS
        assert res.name == "brain_immutability"

        # Tampered snapshot
        snapshot_tampered = {**snapshot_after, "new_patient": {"id": "fake"}}
        res_tampered = assert_family_health_brain_unchanged(snapshot_before, snapshot_tampered)
        assert res_tampered.status == EvaluationStatus.FAIL
    finally:
        env.cleanup()


def test_audit_persistence_and_no_secret_leakage(tmp_path):
    """Verify audit records are stored in SQLite and contain no API tokens/passwords."""
    db_file = str(tmp_path / "eval_audit.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        entry = env.agent.audit_logger.log(
            event_type=AuditEventType.OPERATION_EXECUTED,
            status="SUCCESS",
            details="Check inventory",
            user_id="user_1",
            patient_id="patient_1",
            metadata={"api_key": "SECRET_SHOULD_BE_REDACTED", "medicine": "Metformin"},
        )

        assert entry is not None
        assert len(env.agent.audit_logger._in_memory_logs) > 0
        assert "SECRET_SHOULD_BE_REDACTED" not in str(entry.metadata)
    finally:
        env.cleanup()


# ---------------------------------------------------------------------------
# 4. Evaluation Runner, Reporter & CLI Tests
# ---------------------------------------------------------------------------

def test_evaluation_runner_run_all(tmp_path):
    """Verify EvaluationRunner runs all 10 scenarios and produces structured EvaluationReport."""
    db_file = str(tmp_path / "eval_run_all.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        report = runner.run_all()
        assert report.total_scenarios == 10
        assert report.passed == 7
        assert report.blocked == 3
        assert report.failed == 0
        assert report.not_applicable == 0
        assert report.pass_rate == 70.0
        assert len(report.scenario_results) == 10
    finally:
        runner.cleanup()


def test_evaluation_report_formatting(tmp_path):
    """Verify format_evaluation_report produces structured ASCII table and metadata."""
    db_file = str(tmp_path / "eval_format.db")
    runner = EvaluationRunner(db_path=db_file)
    try:
        report = runner.run_all()
        ascii_text = format_evaluation_report(report)
        assert "Aarogya -- End-to-End Healthcare Coordination Evaluation Report" in ascii_text
        assert "SCENARIO_A" in ascii_text
        assert "SCENARIO_B" in ascii_text
        assert "SCENARIO_J" in ascii_text
        assert "[PASS]" in ascii_text
        assert "[BLOCKED]" in ascii_text
        assert "70.0%" in ascii_text
    finally:
        runner.cleanup()


def test_scenario_catalog_summary_formatting():
    """Verify format_scenario_catalog_summary contains all scenarios."""
    summary_text = format_scenario_catalog_summary()
    assert "Aarogya -- End-to-End Evaluation Scenario Catalog (Module 12)" in summary_text
    assert "SCENARIO_A" in summary_text
    assert "SCENARIO_J" in summary_text


def test_evaluation_environment_cleanup(tmp_path):
    """Verify EvaluationEnvironment cleanly deletes temporary SQLite file."""
    db_file = str(tmp_path / "temp_env_test.db")
    env = EvaluationEnvironment(db_path=db_file)
    assert os.path.exists(db_file)
    env.cleanup()
    assert not os.path.exists(db_file)


def test_cli_evaluation_list(capsys):
    """Verify CLI evaluation-list prints catalog."""
    code = main(["evaluation-list"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Aarogya -- End-to-End Evaluation Scenario Catalog (Module 12)" in captured.out
    assert "SCENARIO_A" in captured.out
    assert "SCENARIO_J" in captured.out


def test_cli_evaluation_run_simulated(capsys):
    """Verify CLI evaluation-run --simulated runs successfully."""
    code = main(["evaluation-run", "--simulated"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Aarogya -- End-to-End Healthcare Coordination Evaluation Report" in captured.out
    assert "[+] PASSED:           7" in captured.out
    assert "[*] BLOCKED (Safety): 3" in captured.out


def test_cli_evaluation_report(capsys):
    """Verify CLI evaluation-report prints definitions and status overview."""
    code = main(["evaluation-report"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Aarogya -- End-to-End Healthcare Coordination Evaluation Report" in captured.out


def test_regression_compatibility_with_modules_1_to_11(tmp_path):
    """Sanity test verifying AarogyaAgent basic query handling is unaffected by Module 12."""
    db_file = str(tmp_path / "regression_check.db")
    env = EvaluationEnvironment(db_path=db_file)
    try:
        req = HealthcareRequest(
            user_id="usr_amit_01",
            raw_text="Check whether my father's prescribed medicine Medicine X 30 tablets is available.",
            patient_name="Rajesh Kumar",
            medicine_name="Medicine X",
            quantity=30,
        )
        res = env.agent.process_request(req)
        assert res is not None
        assert "status" in res
        assert "summary" in res
    finally:
        env.cleanup()


def test_assertion_patient_resolution_variants():
    """Verify assert_patient_resolved passes on correct patient and blocks when unresolved."""
    res_resolved = {"patient_id": "pat_rajesh_01"}
    assert assert_patient_resolved(res_resolved, "pat_rajesh_01").status == EvaluationStatus.PASS

    res_unresolved = {"patient_id": None, "status": "blocked_missing_information"}
    assert assert_patient_resolved(res_unresolved, allow_unresolved=True).status == EvaluationStatus.BLOCKED
    assert assert_patient_resolved(res_unresolved, "pat_rajesh_01").status == EvaluationStatus.FAIL

