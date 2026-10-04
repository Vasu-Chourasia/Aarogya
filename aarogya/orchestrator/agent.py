"""Aarogya LangGraph Orchestrator and Agent Implementation."""

import logging
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, END

from ..config import Settings, ExecutionMode, get_settings
from ..brain.family_health_brain import FamilyHealthBrain
from ..connectors.registry import ConnectorRegistry
from ..connectors.agenticorg_adapter import AgenticOrgAdapter
from ..connectors.pharmacy_connector import (
    PharmacyConnectorInterface,
    MockDirectPharmacyConnector,
    LiveDirectPharmacyConnector,
)
from ..connectors.task_connector import TaskBackendInterface, LocalDevelopmentTaskBackend
from ..policy.authorization_engine import PolicyAuthorizationEngine
from ..understanding.request_parser import RequestUnderstandingService
from ..workflows.medicine_availability import MedicineAvailabilityWorkflow
from ..workflows.caregiver_task import CaregiverTaskWorkflow
from ..workflows.approval_manager import ApprovalManager
from ..workflows.verification import OutcomeVerificationService
from ..workflows.appointment_coordination import AppointmentCoordinationWorkflow
from .audit_logger import AuditLogger
from .state import AarogyaAgentState
from ..models.request import HealthcareRequest
from ..models.enums import (
    RequestType,
    ExecutionStatus,
    AuditEventType,
    ActionType,
    MedicineAvailabilityOutcome,
)

logger = logging.getLogger(__name__)


class AarogyaAgent:
    """Aarogya Family Healthcare Coordinator Agent.
    
    Orchestrates request understanding, patient resolution, capability inspection,
    policy enforcement, HITL approval, operational execution, and outcome verification.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        brain: Optional[FamilyHealthBrain] = None,
        connector_registry: Optional[ConnectorRegistry] = None,
        pharmacy_connector: Optional[PharmacyConnectorInterface] = None,
        task_backend: Optional[TaskBackendInterface] = None,
        persistence_bundle: Optional[Any] = None,
    ):
        self.settings = settings or get_settings()
        self.brain = brain or FamilyHealthBrain()
        self.persistence_bundle = persistence_bundle

        audit_repo = persistence_bundle.audit_repo if persistence_bundle else None
        capability_repo = persistence_bundle.capability_repo if persistence_bundle else None
        sync_history_repo = persistence_bundle.sync_history_repo if persistence_bundle else None
        approval_repo = persistence_bundle.approval_repo if persistence_bundle else None
        execution_repo = persistence_bundle.execution_repo if persistence_bundle else None
        idempotency_repo = persistence_bundle.idempotency_repo if persistence_bundle else None
        appointment_repo = getattr(persistence_bundle, "appointment_repo", None) if persistence_bundle else None
        voice_repo = getattr(persistence_bundle, "voice_repo", None) if persistence_bundle else None

        self.audit_logger = AuditLogger(
            log_file=self.settings.audit_log_file,
            redact_sensitive=self.settings.redact_sensitive_data,
            audit_repo=audit_repo,
        )
        
        # Connectors & Registry
        self.connector_registry = connector_registry or ConnectorRegistry(
            execution_mode=self.settings.execution_mode,
            capability_repo=capability_repo,
            sync_history_repo=sync_history_repo,
        )
        self.agenticorg_adapter = AgenticOrgAdapter(self.settings, self.connector_registry)
        
        # Attempt sync if platform configured
        if self.agenticorg_adapter.is_connected:
            self.agenticorg_adapter.discover_and_sync()

        # Direct Pharmacy Connector
        if pharmacy_connector:
            self.pharmacy_connector = pharmacy_connector
        elif self.settings.pharmacy_connector_enabled and self.settings.pharmacy_api_base_url:
            self.pharmacy_connector = LiveDirectPharmacyConnector(
                base_url=self.settings.pharmacy_api_base_url,
                api_key=self.settings.pharmacy_api_key or "",
                timeout_seconds=self.settings.pharmacy_timeout_seconds,
            )
        else:
            # In simulation mode, attach mock direct pharmacy connector
            self.pharmacy_connector = MockDirectPharmacyConnector()

        # Task Backend
        self.task_backend = task_backend or LocalDevelopmentTaskBackend()

        # Core Services
        self.parser = RequestUnderstandingService(self.brain)
        self.policy_engine = PolicyAuthorizationEngine(self.brain)
        self.approval_manager = ApprovalManager(approval_repo=approval_repo)
        self.verification_service = OutcomeVerificationService(self.settings.execution_mode)
        
        # Workflows
        self.medicine_workflow = MedicineAvailabilityWorkflow(
            brain=self.brain,
            connector_registry=self.connector_registry,
            policy_engine=self.policy_engine,
            pharmacy_connector=self.pharmacy_connector,
            verification_service=self.verification_service,
        )
        self.task_workflow = CaregiverTaskWorkflow(
            brain=self.brain,
            connector_registry=self.connector_registry,
            policy_engine=self.policy_engine,
            approval_manager=self.approval_manager,
            task_backend=self.task_backend,
            verification_service=self.verification_service,
        )

        # Module 9: Controlled Tool Invocation & Execution Gateway
        from .execution_gateway import ExecutionGateway
        self.execution_gateway = ExecutionGateway(
            settings=self.settings,
            brain=self.brain,
            connector_registry=self.connector_registry,
            policy_engine=self.policy_engine,
            approval_manager=self.approval_manager,
            verification_service=self.verification_service,
            audit_logger=self.audit_logger,
            execution_repo=execution_repo,
            idempotency_repo=idempotency_repo,
        )

        # Phase 14: Appointment & Voice Coordination Workflow
        self.appointment_workflow = AppointmentCoordinationWorkflow(
            brain=self.brain,
            policy_engine=self.policy_engine,
            approval_manager=self.approval_manager,
            execution_gateway=self.execution_gateway,
            appointment_repo=appointment_repo,
            voice_repo=voice_repo,
            audit_logger=self.audit_logger,
        )

        # Build LangGraph workflow graph
        self.graph = self._build_langgraph()

    def _build_langgraph(self):
        """Construct LangGraph StateGraph conforming to Phase 2 architecture."""
        builder = StateGraph(AarogyaAgentState)

        # Nodes
        builder.add_node("interpret_request", self._node_interpret_request)
        builder.add_node("resolve_patient_and_rx", self._node_resolve_patient_and_rx)
        builder.add_node("evaluate_policy_and_auth", self._node_evaluate_policy_and_auth)
        builder.add_node("discover_capabilities", self._node_discover_capabilities)
        builder.add_node("decide_and_route", self._node_decide_and_route)
        builder.add_node("execute_operation", self._node_execute_operation)
        builder.add_node("verify_and_finalize", self._node_verify_and_finalize)

        # Edges
        builder.set_entry_point("interpret_request")
        builder.add_edge("interpret_request", "resolve_patient_and_rx")
        builder.add_edge("resolve_patient_and_rx", "evaluate_policy_and_auth")
        builder.add_edge("evaluate_policy_and_auth", "discover_capabilities")
        builder.add_edge("discover_capabilities", "decide_and_route")

        # Conditional routing from decision engine
        builder.add_conditional_edges(
            "decide_and_route",
            self._route_decision,
            {
                "execute": "execute_operation",
                "finalize": "verify_and_finalize",
            },
        )
        builder.add_edge("execute_operation", "verify_and_finalize")
        builder.add_edge("verify_and_finalize", END)

        return builder.compile()

    # --- LangGraph Node Implementations ---

    def _node_interpret_request(self, state: AarogyaAgentState) -> AarogyaAgentState:
        req = state["raw_request"]
        self.audit_logger.log(
            event_type=AuditEventType.REQUEST_RECEIVED,
            status="received",
            details=f"Received healthcare coordination request on channel '{req.channel}'",
            request_id=req.request_id,
            user_id=req.user_id,
            execution_mode=self.settings.execution_mode,
        )

        parsed = self.parser.parse(req)
        return {
            "parsed_request": parsed,
            "patient_id": parsed.patient_id,
            "patient_name": parsed.patient_name,
            "execution_status": parsed.execution_status,
        }

    def _node_resolve_patient_and_rx(self, state: AarogyaAgentState) -> AarogyaAgentState:
        parsed = state["parsed_request"]
        patient_id = state.get("patient_id")
        patient_name = state.get("patient_name")
        patient_resolved = False
        prescription_verified = False
        prescription_id = None

        if patient_id:
            patient = self.brain.get_patient(patient_id)
            if patient:
                patient_resolved = True
                patient_name = patient.full_name
                self.audit_logger.log(
                    event_type=AuditEventType.PATIENT_RESOLVED,
                    status="resolved",
                    details=f"Patient resolved to verified record: {patient.full_name} ({patient.patient_id})",
                    request_id=parsed.request_id,
                    patient_id=patient.patient_id,
                    user_id=parsed.requesting_user,
                    execution_mode=self.settings.execution_mode,
                )

                # Check prescription
                if parsed.medicine_name:
                    rx = self.brain.get_verified_prescription(patient.patient_id, parsed.medicine_name)
                    if rx:
                        prescription_verified = True
                        prescription_id = rx.prescription_id
                        self.audit_logger.log(
                            event_type=AuditEventType.PRESCRIPTION_RESOLVED,
                            status="verified",
                            details=f"Prescription verified: {rx.prescription_id} issued by {rx.doctor_name}",
                            request_id=parsed.request_id,
                            patient_id=patient.patient_id,
                            user_id=parsed.requesting_user,
                            execution_mode=self.settings.execution_mode,
                        )

        return {
            "patient_resolved": patient_resolved,
            "patient_id": patient_id,
            "patient_name": patient_name,
            "prescription_verified": prescription_verified,
            "prescription_id": prescription_id,
        }

    def _node_evaluate_policy_and_auth(self, state: AarogyaAgentState) -> AarogyaAgentState:
        parsed = state["parsed_request"]
        patient_id = state.get("patient_id")
        user_id = parsed.requesting_user
        req_type = parsed.request_type

        is_consequential = self.policy_engine.is_consequential_action(req_type.value)

        # If patient unresolved or missing info, defer authorization
        if not patient_id:
            return {
                "is_authorized": False,
                "authorization_reason": "Patient unresolved",
                "is_consequential": is_consequential,
            }

        is_auth, reason = self.policy_engine.authorize_request(
            user_id=user_id,
            patient_id=patient_id,
            action=req_type.value,
        )

        self.audit_logger.log(
            event_type=AuditEventType.AUTHORIZATION_EVALUATED,
            status="authorized" if is_auth else "unauthorized",
            details=f"Policy evaluation: {reason}",
            request_id=parsed.request_id,
            patient_id=patient_id,
            user_id=user_id,
            execution_mode=self.settings.execution_mode,
        )

        return {
            "is_authorized": is_auth,
            "authorization_reason": reason,
            "is_consequential": is_consequential,
        }

    def _node_discover_capabilities(self, state: AarogyaAgentState) -> AarogyaAgentState:
        parsed = state["parsed_request"]
        req_type = parsed.request_type

        integration = "pharmacy" if req_type in [RequestType.MEDICINE_AVAILABILITY_CHECK, RequestType.MEDICINE_ORDER, RequestType.REFILL_COORDINATION] else "task_manager"
        required_capability = "check_medicine_availability" if req_type in [RequestType.MEDICINE_AVAILABILITY_CHECK, RequestType.REFILL_COORDINATION] else "create_caregiver_task"

        is_sim_mode = self.settings.execution_mode == ExecutionMode.SIMULATION
        cap_result = self.connector_registry.check_capability(
            integration=integration,
            required_capability=required_capability,
            allow_simulation=is_sim_mode,
        )

        self.audit_logger.log(
            event_type=AuditEventType.CAPABILITY_CHECK_COMPLETED,
            status="available" if cap_result.available else "unavailable",
            details=f"Capability check for '{integration}.{required_capability}': {cap_result.reason}",
            request_id=parsed.request_id,
            patient_id=state.get("patient_id"),
            user_id=parsed.requesting_user,
            execution_mode=self.settings.execution_mode,
            metadata={"is_simulation": cap_result.is_simulation},
        )

        return {"capability_check": cap_result}

    def _node_decide_and_route(self, state: AarogyaAgentState) -> AarogyaAgentState:
        parsed = state["parsed_request"]
        cap_result = state.get("capability_check")
        is_auth = state.get("is_authorized", False)
        is_consequential = state.get("is_consequential", False)

        # Emergency Priority Routing: Immediate safety intervention
        if parsed.request_type == RequestType.EMERGENCY or parsed.execution_status == ExecutionStatus.ROUTED_TO_EMERGENCY:
            return {
                "execution_status": ExecutionStatus.ROUTED_TO_EMERGENCY,
                "error_message": "Immediate emergency medical attention required.",
            }

        # Decision 1: Missing information
        if parsed.missing_information:
            return {
                "execution_status": ExecutionStatus.BLOCKED_MISSING_INFORMATION,
                "error_message": f"Missing information: {', '.join(m.description for m in parsed.missing_information)}",
            }

        # Decision 2: Unauthorized
        if not is_auth:
            return {
                "execution_status": ExecutionStatus.BLOCKED_UNAUTHORIZED,
                "error_message": state.get("authorization_reason", "Unauthorized operation"),
            }

        # Decision 3: Connector missing or unhealthy
        if cap_result and not cap_result.available:
            return {
                "execution_status": ExecutionStatus.BLOCKED_CONNECTOR_MISSING,
                "error_message": cap_result.reason,
            }

        # Decision 4: Consequential action requires human approval
        if is_consequential:
            return {
                "execution_status": ExecutionStatus.AWAITING_APPROVAL,
            }

        # Decision 5: Ready to execute
        return {
            "execution_status": ExecutionStatus.READY_FOR_EXECUTION,
        }

    def _route_decision(self, state: AarogyaAgentState) -> str:
        status = state.get("execution_status")
        if status == ExecutionStatus.READY_FOR_EXECUTION:
            return "execute"
        return "finalize"

    def _node_execute_operation(self, state: AarogyaAgentState) -> AarogyaAgentState:
        parsed = state["parsed_request"]
        req_type = parsed.request_type

        if req_type in [RequestType.MEDICINE_AVAILABILITY_CHECK, RequestType.REFILL_COORDINATION]:
            # Also route through ExecutionGateway for 10-gate policy check, SQLite persistence & audit
            if self.execution_gateway and parsed.medicine_name:
                from ..models.gateway import ExecutionRequest
                gw_req = ExecutionRequest(
                    request_id=f"gw_{parsed.request_id}",
                    capability_id="conn:apollo_pharmacy",
                    requested_operation="check_inventory",
                    input_payload={
                        "medicine_name": parsed.medicine_name,
                        "quantity": parsed.required_quantity or 30,
                    },
                    requesting_user_id=parsed.requesting_user,
                    patient_id=state.get("patient_id"),
                    workflow_id="medicine_availability",
                    execution_mode=self.settings.execution_mode,
                )
                try:
                    self.execution_gateway.execute(gw_req)
                except Exception as e:
                    logger.warning("Gateway check during agent execution: %s", str(e))

            result = self.medicine_workflow.process_availability_check(parsed)
            self.audit_logger.log(
                event_type=AuditEventType.OPERATION_EXECUTED,
                status=result.outcome.value,
                details=f"Medicine availability check outcome: {result.outcome.value} from source '{result.source}'",
                request_id=parsed.request_id,
                patient_id=state.get("patient_id"),
                user_id=parsed.requesting_user,
                execution_mode=self.settings.execution_mode,
            )
            return {
                "medicine_result": result,
                "execution_status": ExecutionStatus.EXECUTED,
            }

        elif req_type == RequestType.APPOINTMENT_COORDINATION:
            from ..models.appointment import AppointmentRequest, ClinicInfo
            clinic_name = parsed.preferred_pharmacy or "City Health Clinic"
            apt_req = AppointmentRequest(
                request_id=parsed.request_id,
                patient_id=state.get("patient_id") or "pat_rajesh_01",
                requesting_user_id=parsed.requesting_user,
                clinic=ClinicInfo(
                    clinic_id="cln_city_01",
                    clinic_name=clinic_name,
                ),
                preferred_date="2026-10-15",
                preferred_time="10:00 AM",
                reason_for_visit=getattr(parsed, "raw_text", None),
            )
            success, msg, apt_rec = self.appointment_workflow.initiate_coordination(apt_req)
            return {
                "execution_status": ExecutionStatus.EXECUTED if success else ExecutionStatus.FAILED,
                "error_message": None if success else msg,
                "metadata": {"appointment_record": apt_rec.model_dump() if apt_rec else None},
            }

        return state

    def _node_verify_and_finalize(self, state: AarogyaAgentState) -> AarogyaAgentState:
        parsed = state["parsed_request"]
        status = state.get("execution_status")
        medicine_result = state.get("medicine_result")
        cap_check = state.get("capability_check")
        err_msg = state.get("error_message")

        response: Dict[str, Any] = {
            "request_id": parsed.request_id,
            "user_id": parsed.requesting_user,
            "request_type": parsed.request_type.value,
            "patient_name": state.get("patient_name"),
            "patient_id": state.get("patient_id"),
            "execution_mode": self.settings.execution_mode.value,
            "status": status.value if status else "unknown",
            "is_simulated": self.settings.execution_mode == ExecutionMode.SIMULATION,
        }

        # Case A: Missing Information
        if status == ExecutionStatus.BLOCKED_MISSING_INFORMATION:
            response["summary"] = "Request blocked due to missing information."
            response["missing_information"] = [
                {"field": m.field, "question": m.clarification_question}
                for m in parsed.missing_information
            ]
            response["next_step"] = "Please provide the requested details."

        # Case B: Connector Missing
        elif status == ExecutionStatus.BLOCKED_CONNECTOR_MISSING:
            response["summary"] = f"Operation blocked: required integration is unavailable."
            response["blocker_reason"] = err_msg
            response["missing_requirements"] = [
                "Configured external provider connector",
                "Healthy network connection & valid credentials",
                "AgenticOrg tenant tool authorization",
            ]
            response["claim_safeguard"] = "No medicine availability or order claim was fabricated."

        # Case C: Unauthorized
        elif status == ExecutionStatus.BLOCKED_UNAUTHORIZED:
            response["summary"] = "Operation blocked: User is not authorized for this patient or action."
            response["blocker_reason"] = err_msg

        # Case Emergency Routing
        elif status == ExecutionStatus.ROUTED_TO_EMERGENCY:
            response["summary"] = "CRITICAL EMERGENCY DETECTED: Immediate emergency medical assistance required."
            response["emergency_guidance"] = (
                "Please call 108 / 112 (or your local emergency services) immediately or proceed to the "
                "nearest hospital emergency department. Do not delay urgent care to arrange routine medication delivery or tasks."
            )
            response["disclaimer"] = "Aarogya is an AI family healthcare coordinator, not an emergency medical responder."
            response["is_emergency"] = True

        # Case D: Awaiting Approval (Consequential actions like Task Creation)
        elif status == ExecutionStatus.AWAITING_APPROVAL:
            # Propose task via task workflow
            success, msg, approval_data = self.task_workflow.propose_task(
                request_id=parsed.request_id,
                user_id=parsed.requesting_user,
                patient_id=state.get("patient_id", ""),
                task_description=f"Refill coordination for {parsed.medicine_name or 'prescribed medicine'}",
                assigned_caregiver=parsed.requesting_user,
                medicine_reference=parsed.medicine_name,
                required_quantity=parsed.required_quantity,
            )
            response["summary"] = "Consequential action requires explicit human approval."
            response["approval_data"] = approval_data
            response["next_step"] = "Review proposed parameters and grant explicit approval to proceed."

        # Case E: Executed Medicine Availability Check
        elif status == ExecutionStatus.EXECUTED and medicine_result:
            response["summary"] = f"Medicine availability check completed: {medicine_result.outcome.value}."
            response["availability"] = {
                "outcome": medicine_result.outcome.value,
                "medicine_name": medicine_result.medicine_name,
                "required_quantity": medicine_result.required_quantity,
                "available_quantity": medicine_result.available_quantity,
                "pharmacy_name": medicine_result.pharmacy_name,
                "unit_price": medicine_result.unit_price,
                "total_estimated_price": medicine_result.total_estimated_price,
                "source": medicine_result.source,
                "details": medicine_result.details,
            }
            if medicine_result.outcome == MedicineAvailabilityOutcome.UNAVAILABLE:
                response["recommendation"] = "Medicine is currently out of stock. You may request creating a caregiver task to follow up or explore alternative licensed pharmacies."
            elif medicine_result.outcome == MedicineAvailabilityOutcome.AVAILABLE:
                response["recommendation"] = "Medicine is available in stock. Order placement requires explicit authorization."

        self.audit_logger.log(
            event_type=AuditEventType.VERIFICATION_COMPLETED,
            status="completed",
            details=f"Request finalized with status '{status.value if status else 'unknown'}'",
            request_id=parsed.request_id,
            patient_id=state.get("patient_id"),
            user_id=parsed.requesting_user,
            execution_mode=self.settings.execution_mode,
        )

        return {"final_response": response}

    # --- Public Invocation Interface ---

    def process_request(self, request: HealthcareRequest) -> Dict[str, Any]:
        """Entry point for handling a user request through the LangGraph pipeline."""
        initial_state: AarogyaAgentState = {
            "raw_request": request,
        }
        final_state = self.graph.invoke(initial_state)
        return final_state.get("final_response", {})
