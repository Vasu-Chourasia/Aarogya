"""Module 12: Deterministic Evaluation Runner.

Executes evaluation scenarios through the complete Aarogya architecture:
Request -> Intent Understanding -> Patient Resolution -> Verified Health Context
-> Capability Resolution -> Authorization -> Approval -> Execution Policy
-> Controlled Tool Invocation -> Outcome Verification -> Persistence -> Caregiver Notification.
"""

import os
import copy
import tempfile
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..config import Settings, ExecutionMode
from ..brain.family_health_brain import FamilyHealthBrain
from ..connectors.registry import ConnectorRegistry
from ..connectors.pharmacy_adapter import MockPharmacyProvider, get_pharmacy_adapter
from ..connectors.pharmacy_connector import MockDirectPharmacyConnector
from ..orchestrator.agent import AarogyaAgent
from ..orchestrator.audit_logger import AuditLogger
from ..persistence import get_persistence_bundle, PersistenceBundle
from ..models.request import HealthcareRequest
from ..models.gateway import ExecutionRequest
from ..models.connector import NormalizedCapability
from ..models.enums import (
    HealthcareDomain,
    GatewayExecutionStatus,
    AuditEventType,
    ExecutionStatus,
    MedicineAvailabilityOutcome,
    VerificationStatus,
)
from .scenario_models import (
    EvaluationStatus,
    AssertionResult,
    ScenarioContext,
    ScenarioResult,
    EvaluationReport,
)
from .scenario_catalog import SCENARIOS, get_scenario, list_all_scenarios
from .assertions import (
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

logger = logging.getLogger(__name__)


class EvaluationEnvironment:
    """Manages an isolated synthetic evaluation environment with durable SQLite persistence."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.path.join(tempfile.gettempdir(), f"aarogya_eval_{os.getpid()}_{datetime.utcnow().strftime('%f')}.db")
        self.settings = Settings(
            execution_mode=ExecutionMode.SIMULATION,
            live_execution_enabled=False,
            pharmacy_live_operations_enabled=False,
            sqlite_db_path=self._db_path,
        )
        self.bundle: PersistenceBundle = get_persistence_bundle(self._db_path)
        self.brain = FamilyHealthBrain(seed_fictional_data=True)
        self._seed_capabilities()
        self.registry = ConnectorRegistry(
            execution_mode=self.settings.execution_mode,
            capability_repo=self.bundle.capability_repo,
            sync_history_repo=self.bundle.sync_history_repo,
        )
        self.pharmacy_adapter = MockPharmacyProvider(provider_name="Apollo Direct (Mock Provider)")
        self.agent = AarogyaAgent(
            settings=self.settings,
            brain=self.brain,
            connector_registry=self.registry,
            persistence_bundle=self.bundle,
        )

    def _seed_capabilities(self) -> None:
        """Seed verified capabilities in isolated capability repository."""
        cap_pharm = NormalizedCapability(
            capability_id="conn:apollo_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="apollo_pharmacy",
            display_name="Apollo Direct Pharmacy API",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory", "get_product_details", "get_price", "check_delivery_coverage", "get_order_status"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
        )
        self.bundle.capability_repo.save(cap_pharm)

        cap_task = NormalizedCapability(
            capability_id="conn:task_backend",
            source_platform="local",
            tenant_connector_id="task_backend",
            display_name="Local Caregiver Task Backend",
            domain=HealthcareDomain.CAREGIVER_TASKS,
            supported_operations=["create_caregiver_task", "update_task_status"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
        )
        self.bundle.capability_repo.save(cap_task)

    def capture_brain_snapshot(self) -> Dict[str, Any]:
        """Capture deep copy snapshot of Family Health Brain state."""
        return {
            p_id: copy.deepcopy(p_rec.model_dump())
            for p_id, p_rec in self.brain._patients.items()
        }

    def cleanup(self) -> None:
        """Close DB connection and delete isolated temporary DB file."""
        try:
            self.bundle.store.close()
        except Exception:
            pass
        if os.path.exists(self._db_path):
            try:
                os.remove(self._db_path)
            except Exception:
                pass


class EvaluationRunner:
    """Deterministic runner executing scenarios across the complete Aarogya stack."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def cleanup(self) -> None:
        """Clean up isolated database file if specified."""
        if self.db_path and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass


    def run_scenario(self, scenario_id: str) -> ScenarioResult:
        """Run a single scenario by ID in an isolated environment."""
        context = get_scenario(scenario_id)
        env = EvaluationEnvironment(db_path=self.db_path)
        try:
            return self._execute_scenario(env, context)
        finally:
            env.cleanup()

    def run_all(self) -> EvaluationReport:
        """Run all 10 catalog scenarios and compile aggregate report."""
        env = EvaluationEnvironment(db_path=self.db_path)
        scenario_results: List[ScenarioResult] = []
        try:
            for ctx in list_all_scenarios():
                res = self._execute_scenario(env, ctx)
                scenario_results.append(res)

            passed_count = sum(1 for r in scenario_results if r.status == EvaluationStatus.PASS)
            blocked_count = sum(1 for r in scenario_results if r.status == EvaluationStatus.BLOCKED)
            failed_count = sum(1 for r in scenario_results if r.status == EvaluationStatus.FAIL)
            na_count = sum(1 for r in scenario_results if r.status == EvaluationStatus.NOT_APPLICABLE)

            summary = (
                f"Evaluation Completed: {len(scenario_results)} Total Scenarios | "
                f"{passed_count} Passed | {blocked_count} Blocked by Safety Policy | "
                f"{failed_count} Failed | {na_count} Not Applicable. "
                f"Live Execution: DISABLED. All operations confined to safe simulation."
            )

            return EvaluationReport(
                total_scenarios=len(scenario_results),
                passed=passed_count,
                failed=failed_count,
                blocked=blocked_count,
                not_applicable=na_count,
                scenario_results=scenario_results,
                summary=summary,
                timestamp=datetime.utcnow(),
                execution_mode="SIMULATION",
                provider_mode="mock",
                live_execution_enabled=False,
            )
        finally:
            env.cleanup()

    def _execute_scenario(self, env: EvaluationEnvironment, ctx: ScenarioContext) -> ScenarioResult:
        """Internal dispatch executing a scenario and gathering assertions."""
        assertions: List[AssertionResult] = []
        brain_before = env.capture_brain_snapshot()
        req_id = f"eval_req_{ctx.scenario_id.lower()}_{datetime.utcnow().strftime('%f')}"

        # Common baseline assertions: Live execution strictly disabled
        assertions.append(assert_no_live_execution(env.agent))

        agent_response: Optional[Dict[str, Any]] = None
        gw_result: Optional[Dict[str, Any]] = None
        status = EvaluationStatus.PASS

        # Dispatch scenario logic
        if ctx.scenario_id == "SCENARIO_A":
            # Scenario A: Refill Coordination
            req = HealthcareRequest(
                request_id=req_id,
                user_id=ctx.user_id,
                raw_text=ctx.request_text,
                patient_name=ctx.patient_name,
                patient_relationship=ctx.patient_relationship,
                medicine_name=ctx.medicine_name,
                quantity=ctx.quantity,
            )
            agent_response = env.agent.process_request(req)
            assertions.append(assert_patient_resolved(agent_response, "pat_rajesh_01"))
            assertions.append(assert_authorization_enforced(agent_response, should_be_authorized=True))
            assertions.append(assert_capability_verified(agent_response, expected_available=True))
            assertions.append(assert_no_fabricated_data(agent_response))
            assertions.append(assert_audit_records_persisted(env.bundle.audit_repo, req_id))
            status = EvaluationStatus.PASS

        elif ctx.scenario_id == "SCENARIO_B":
            # Scenario B: Unauthorized Family Member
            req = HealthcareRequest(
                request_id=req_id,
                user_id=ctx.user_id,
                raw_text=ctx.request_text,
                patient_name=ctx.patient_name,
                medicine_name=ctx.medicine_name,
                quantity=ctx.quantity,
            )
            agent_response = env.agent.process_request(req)
            auth_assert = assert_authorization_enforced(agent_response, should_be_authorized=False)
            assertions.append(auth_assert)
            assertions.append(assert_no_unauthorized_disclosure(agent_response))
            assertions.append(assert_audit_records_persisted(env.bundle.audit_repo, req_id))
            status = EvaluationStatus.BLOCKED

        elif ctx.scenario_id == "SCENARIO_C":
            # Scenario C: Missing Patient Identity
            req = HealthcareRequest(
                request_id=req_id,
                user_id=ctx.user_id,
                raw_text=ctx.request_text,
                medicine_name=ctx.medicine_name,
                quantity=ctx.quantity,
            )
            agent_response = env.agent.process_request(req)
            assertions.append(assert_patient_resolved(agent_response, allow_unresolved=True))
            status = EvaluationStatus.BLOCKED

        elif ctx.scenario_id == "SCENARIO_D":
            # Scenario D: Provider Timeout
            gw_req = ExecutionRequest(
                request_id=req_id,
                capability_id="conn:apollo_pharmacy",
                requested_operation="check_inventory",
                input_payload={"medicine_name": "TriggerTimeout", "quantity": 30},
                requesting_user_id=ctx.user_id,
                patient_id="pat_rajesh_01",
                workflow_id="medicine_availability",
                execution_mode=ExecutionMode.SIMULATION,
            )
            res = env.agent.execution_gateway.execute(gw_req)
            gw_result = res.model_dump(mode="json")
            if res.status == GatewayExecutionStatus.TIMED_OUT and res.error_category == "TIMEOUT":
                assertions.append(AssertionResult(
                    name="provider_timeout_handled",
                    status=EvaluationStatus.PASS,
                    message="Provider timeout caught and mapped to TIMEOUT category without data fabrication.",
                ))
            else:
                assertions.append(AssertionResult(
                    name="provider_timeout_handled",
                    status=EvaluationStatus.FAIL,
                    message=f"Expected TIMED_OUT status, got {res.status}.",
                ))
            assertions.append(assert_audit_records_persisted(env.bundle.audit_repo, req_id))
            status = EvaluationStatus.PASS

        elif ctx.scenario_id == "SCENARIO_E":
            # Scenario E: Missing/Unprescribed Medicine
            req = HealthcareRequest(
                request_id=req_id,
                user_id=ctx.user_id,
                raw_text=ctx.request_text,
                patient_name=ctx.patient_name,
                medicine_name=ctx.medicine_name,
                quantity=ctx.quantity,
            )
            agent_response = env.agent.process_request(req)
            # Must reject unprescribed medicine
            med_res = agent_response.get("availability", {})
            if agent_response.get("status") in ("blocked_missing_information", "executed") and med_res.get("outcome") == "MISSING_PRESCRIPTION":
                assertions.append(AssertionResult(
                    name="unverified_medicine_rejected",
                    status=EvaluationStatus.BLOCKED,
                    message="Unverified prescription drug check rejected safely without clinical modification.",
                ))
                status = EvaluationStatus.BLOCKED
            else:
                assertions.append(AssertionResult(
                    name="unverified_medicine_rejected",
                    status=EvaluationStatus.FAIL,
                    message="Expected rejection of unprescribed medicine.",
                ))
                status = EvaluationStatus.FAIL

        elif ctx.scenario_id == "SCENARIO_F":
            # Scenario F: HITL Approval Required
            from ..models.enums import ActionType
            app_req = env.agent.approval_manager.request_approval(
                request_id=req_id,
                user_identity=ctx.user_id,
                action_type=ActionType.CREATE_CAREGIVER_TASK,
                parameters={"medicine_name": "Medicine X", "quantity": 30},
                is_simulation=True,
            )
            assertions.append(assert_hitl_binding_integrity(
                approval_record=app_req,
                expected_user_id=ctx.user_id,
                expected_patient_id="pat_rajesh_01",
                expected_action="create_caregiver_task",
            ))
            # Test approval parameter mismatch rejection
            success, msg, _ = env.agent.approval_manager.grant_approval(
                approval_id=app_req.approval_id,
                user_identity=ctx.user_id,
                provided_parameters={"medicine_name": "Medicine X", "quantity": 999},  # Tampered quantity!
            )
            if not success:
                assertions.append(AssertionResult(
                    name="tampered_parameters_rejected",
                    status=EvaluationStatus.PASS,
                    message="Tampered parameter hash rejected approval grant.",
                ))
            else:
                assertions.append(AssertionResult(
                    name="tampered_parameters_rejected",
                    status=EvaluationStatus.FAIL,
                    message="Approval accepted tampered parameters!",
                ))
            status = EvaluationStatus.PASS

        elif ctx.scenario_id == "SCENARIO_G":
            # Scenario G: Duplicate Request / Idempotency
            idemp_key = ctx.idempotency_key or "idemp_dup_test_01"
            gw_req1 = ExecutionRequest(
                request_id=f"{req_id}_1",
                capability_id="conn:apollo_pharmacy",
                requested_operation="check_inventory",
                input_payload={"medicine_name": "Medicine X", "quantity": 30},
                requesting_user_id=ctx.user_id,
                patient_id="pat_rajesh_01",
                idempotency_key=idemp_key,
                execution_mode=ExecutionMode.SIMULATION,
            )
            res1 = env.agent.execution_gateway.execute(gw_req1)
            gw_req2 = ExecutionRequest(
                request_id=f"{req_id}_2",
                capability_id="conn:apollo_pharmacy",
                requested_operation="check_inventory",
                input_payload={"medicine_name": "Medicine X", "quantity": 30},
                requesting_user_id=ctx.user_id,
                patient_id="pat_rajesh_01",
                idempotency_key=idemp_key,
                execution_mode=ExecutionMode.SIMULATION,
            )
            res2 = env.agent.execution_gateway.execute(gw_req2)
            assertions.append(assert_idempotency_enforced(res1, res2))
            status = EvaluationStatus.PASS

        elif ctx.scenario_id == "SCENARIO_H":
            # Scenario H: Uncertain Outcome After Execution
            idemp_key = ctx.idempotency_key or "idemp_uncertain_test_01"
            from ..models.gateway import ExecutionResult
            from ..models.enums import CapabilityPolicyDecision
            # Simulate a crashed/interrupted execution recorded as UNKNOWN_OUTCOME
            uncertain_res = ExecutionResult(
                execution_id=f"exec_{req_id}_crashed",
                request_id=f"{req_id}_crashed",
                capability_id="conn:apollo_pharmacy",
                operation="check_inventory",
                status=GatewayExecutionStatus.UNKNOWN_OUTCOME,
                policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                verification_status=VerificationStatus.PENDING_VERIFICATION,
                error_category="NETWORK_DISPATCH_LOST",
                error_message="Provider connection lost after dispatch.",
                timestamp=datetime.utcnow(),
            )
            env.agent.execution_gateway._idempotency_store[idemp_key] = uncertain_res
            if env.bundle.execution_repo:
                env.bundle.execution_repo.save_execution(uncertain_res)
            if env.bundle.idempotency_repo:
                env.bundle.idempotency_repo.claim_key(
                    idempotency_key=idemp_key,
                    execution_id=f"exec_{req_id}_crashed",
                    user_id=ctx.user_id,
                    operation="check_inventory",
                    request_fingerprint="fp_uncertain_001",
                )
                env.bundle.idempotency_repo.update_status(idemp_key, "UNKNOWN_OUTCOME")

            # Attempt retry with same idempotency key
            retry_req = ExecutionRequest(
                request_id=f"{req_id}_retry",
                capability_id="conn:apollo_pharmacy",
                requested_operation="check_inventory",
                input_payload={"medicine_name": "Medicine X", "quantity": 30},
                requesting_user_id=ctx.user_id,
                patient_id="pat_rajesh_01",
                idempotency_key=idemp_key,
                execution_mode=ExecutionMode.SIMULATION,
            )
            res_retry = env.agent.execution_gateway.execute(retry_req)
            assertions.append(assert_uncertain_outcome_requires_verification(res_retry))
            status = EvaluationStatus.PASS

        elif ctx.scenario_id == "SCENARIO_I":
            # Scenario I: Caregiver Notification
            patient = env.brain.get_patient("pat_rajesh_01")
            assertions.append(assert_notification_authorized(
                recipient_id=ctx.user_id,
                patient_family_members=patient.family_members if patient else [],
            ))
            # Test stranger notification rejection
            stranger_assert = assert_notification_authorized(
                recipient_id="usr_stranger_99",
                patient_family_members=patient.family_members if patient else [],
            )
            if stranger_assert.status == EvaluationStatus.FAIL:
                assertions.append(AssertionResult(
                    name="unauthorized_caregiver_notification_rejected",
                    status=EvaluationStatus.PASS,
                    message="Unauthorized stranger excluded from caregiver notifications.",
                ))
            status = EvaluationStatus.PASS

        elif ctx.scenario_id == "SCENARIO_J":
            # Scenario J: Emergency / Urgent Symptoms
            req = HealthcareRequest(
                request_id=req_id,
                user_id=ctx.user_id,
                raw_text=ctx.request_text,
                patient_name=ctx.patient_name,
            )
            agent_response = env.agent.process_request(req)
            assertions.append(assert_emergency_safety_routed(agent_response))
            assertions.append(assert_audit_records_persisted(env.bundle.audit_repo, req_id))
            status = EvaluationStatus.PASS

        # Invariant assertion: Family Health Brain was NOT mutated
        brain_after = env.capture_brain_snapshot()
        assertions.append(assert_family_health_brain_unchanged(brain_before, brain_after))

        # Check if any assertion failed
        has_failure = any(a.status == EvaluationStatus.FAIL for a in assertions)
        if has_failure:
            status = EvaluationStatus.FAIL

        # Count audit events
        audit_events = env.bundle.audit_repo.list_events(request_id=req_id) if env.bundle.audit_repo else []

        return ScenarioResult(
            scenario_id=ctx.scenario_id,
            title=ctx.title,
            description=ctx.description,
            status=status,
            assertions=assertions,
            agent_response=agent_response,
            gateway_result=gw_result,
            safety_violations=[a.message for a in assertions if a.status == EvaluationStatus.FAIL],
            audit_events_count=len(audit_events),
            execution_mode="SIMULATION",
            provider_mode="mock",
            live_execution_enabled=False,
            diagnostics={
                "request_id": req_id,
                "assertions_count": len(assertions),
                "passed_assertions": sum(1 for a in assertions if a.status == EvaluationStatus.PASS),
                "blocked_assertions": sum(1 for a in assertions if a.status == EvaluationStatus.BLOCKED),
            },
        )
