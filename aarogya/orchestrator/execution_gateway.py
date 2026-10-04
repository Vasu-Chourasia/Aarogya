"""Module 9: Controlled Tool Invocation & Execution Gateway.

Centralized, policy-governed execution gateway ensuring that no Aarogya workflow
invokes connector or MCP tools without independent verification of capability readiness,
healthcare authorization, HITL approvals, input safety, and execution mode boundaries.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List, Type, Tuple, Set
from pydantic import BaseModel, ValidationError

from ..config import Settings, ExecutionMode, get_settings
from ..brain.family_health_brain import FamilyHealthBrain
from ..connectors.registry import ConnectorRegistry
from ..policy.authorization_engine import PolicyAuthorizationEngine
from ..workflows.approval_manager import ApprovalManager
from ..workflows.verification import OutcomeVerificationService
from ..orchestrator.audit_logger import AuditLogger
from ..models.enums import (
    GatewayExecutionStatus,
    CapabilityPolicyDecision,
    VerificationStatus,
    ApprovalStatus,
    AuditEventType,
)
from ..models.approval import compute_parameter_hash
from ..models.pharmacy import PharmacyErrorCategory, PharmacyAdapterException
from ..models.gateway import (
    ExecutionRequest,
    ExecutionResult,
    CheckInventoryInputContract,
    GetProductDetailsInputContract,
    GetPriceInputContract,
    CheckDeliveryCoverageInputContract,
    GetOrderStatusInputContract,
    ReserveStockInputContract,
    CreateOrderInputContract,
    CreateCaregiverTaskInputContract,
    QueryCaregiverTaskInputContract,
    InitiatePaymentInputContract,
    TrackDeliveryInputContract,
    DiscoverSlotsInputContract,
    BookAppointmentInputContract,
    InitiateVoiceCallInputContract,
)
from ..connectors.pharmacy_adapter import PharmacyProviderInterface, get_pharmacy_adapter

logger = logging.getLogger(__name__)


# Explicit Operation Allowlist (Section 6)
GLOBAL_OPERATION_ALLOWLIST: Set[str] = {
    # Direct Pharmacy Operations
    "check_inventory",
    "get_product_details",
    "get_price",
    "check_delivery_coverage",
    "reserve_stock",
    "create_order",
    "get_order_status",
    "check_medicine_availability",
    # Caregiver Task Operations
    "create_caregiver_task",
    "query_caregiver_task",
    "update_caregiver_task",
    "cancel_caregiver_task",
    # Payment Operations
    "initiate_payment",
    "verify_payment_status",
    # Logistics Operations
    "track_delivery",
    "schedule_pickup",
    # Voice Communication
    "initiate_voice_call",
    "get_call_status",
    # Phase 14: Appointment Operations
    "discover_appointment_slots",
    "book_appointment",
}


class HandlerRegistration(BaseModel):
    """Metadata and binding for an approved operational handler."""
    capability_pattern: str
    operation: str
    is_consequential: bool
    requires_approval: bool
    validator_cls: Optional[Any] = None
    handler_fn: Any = None


class ExecutionGateway:
    """Centralized policy-governed execution gateway for Aarogya."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        brain: Optional[FamilyHealthBrain] = None,
        connector_registry: Optional[ConnectorRegistry] = None,
        policy_engine: Optional[PolicyAuthorizationEngine] = None,
        approval_manager: Optional[ApprovalManager] = None,
        verification_service: Optional[OutcomeVerificationService] = None,
        audit_logger: Optional[AuditLogger] = None,
        execution_repo: Optional[Any] = None,
        idempotency_repo: Optional[Any] = None,
        pharmacy_adapter: Optional[PharmacyProviderInterface] = None,
    ):
        self.settings = settings or get_settings()
        self.brain = brain or FamilyHealthBrain()
        self.connector_registry = connector_registry or ConnectorRegistry(
            execution_mode=self.settings.execution_mode
        )
        self.policy_engine = policy_engine or PolicyAuthorizationEngine(self.brain)
        self.approval_manager = approval_manager or ApprovalManager()
        self.verification_service = verification_service or OutcomeVerificationService(
            execution_mode=self.settings.execution_mode
        )
        self.audit_logger = audit_logger or AuditLogger(
            log_file=self.settings.audit_log_file,
            redact_sensitive=self.settings.redact_sensitive_data,
        )
        self.execution_repo = execution_repo
        self.idempotency_repo = idempotency_repo
        self.pharmacy_adapter = pharmacy_adapter or get_pharmacy_adapter(self.settings)

        self._idempotency_store: Dict[str, ExecutionResult] = {}
        self._execution_history: List[ExecutionResult] = []
        self._handlers: Dict[Tuple[str, str], HandlerRegistration] = {}

        # Run crash recovery on startup to catch interrupted in-flight executions
        if self.execution_repo:
            try:
                recovered = self.execution_repo.recover_interrupted_executions()
                if recovered:
                    self.audit_logger.log(
                        event_type=AuditEventType.GATEWAY_VERIFICATION_REQUIRED,
                        status="recovered",
                        details=f"Crash recovery identified {len(recovered)} interrupted executions: {recovered}",
                        execution_mode=self.settings.execution_mode,
                    )
            except Exception as e:
                logger.warning("Crash recovery could not be run: %s", str(e))

        self._register_default_handlers()

    @property
    def registered_handlers_count(self) -> int:
        return len(self._handlers)

    @property
    def idempotency_cache_size(self) -> int:
        return len(self._idempotency_store)

    @property
    def execution_history(self) -> List[ExecutionResult]:
        if self.execution_repo:
            try:
                persisted = self.execution_repo.list_executions()
                if persisted:
                    return persisted
            except Exception:
                pass
        return list(self._execution_history)

    # --------------------------------------------------------------------------
    # Default Simulated Handlers
    # --------------------------------------------------------------------------
    def _register_default_handlers(self) -> None:
        """Register deterministic simulated handlers for allowlisted operations."""

        # 1. Pharmacy: check_inventory / check_medicine_availability
        def handle_check_inventory(req: ExecutionRequest) -> Dict[str, Any]:
            med = req.input_payload.get("medicine_name", "")
            pid = req.input_payload.get("product_id")
            qty = req.input_payload.get("quantity", 1)
            inv = self.pharmacy_adapter.check_inventory(product_id=pid, medicine_name=med, quantity=qty)
            return {
                "available": inv.availability_status in ("IN_STOCK", "LOW_STOCK"),
                "medicine_name": inv.medicine_name or med,
                "product_id": inv.product_id,
                "requested_quantity": qty,
                "stock_count": inv.quantity if inv.quantity is not None else 50,
                "availability_status": inv.availability_status,
                "unit_price": 14.50,
                "currency": "INR",
                "provider": inv.provider_reference,
                "is_simulated": inv.is_simulated,
            }

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="check_inventory",
            is_consequential=False,
            requires_approval=False,
            validator_cls=CheckInventoryInputContract,
            handler_fn=handle_check_inventory,
        )
        self.register_handler(
            capability_pattern="conn:pharmacy",
            operation="check_medicine_availability",
            is_consequential=False,
            requires_approval=False,
            validator_cls=CheckInventoryInputContract,
            handler_fn=handle_check_inventory,
        )

        # 1b. Pharmacy: get_product_details
        def handle_get_product_details(req: ExecutionRequest) -> Dict[str, Any]:
            med = req.input_payload.get("medicine_name")
            pid = req.input_payload.get("product_id")
            details = self.pharmacy_adapter.get_product_details(product_id=pid, medicine_name=med)
            return details.model_dump(mode="json")

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="get_product_details",
            is_consequential=False,
            requires_approval=False,
            validator_cls=GetProductDetailsInputContract,
            handler_fn=handle_get_product_details,
        )
        self.register_handler(
            capability_pattern="conn:pharmacy",
            operation="get_product_details",
            is_consequential=False,
            requires_approval=False,
            validator_cls=GetProductDetailsInputContract,
            handler_fn=handle_get_product_details,
        )

        # 1c. Pharmacy: get_price
        def handle_get_price(req: ExecutionRequest) -> Dict[str, Any]:
            med = req.input_payload.get("medicine_name")
            pid = req.input_payload.get("product_id")
            qty = req.input_payload.get("quantity", 1)
            price_details = self.pharmacy_adapter.get_price(product_id=pid, medicine_name=med, quantity=qty)
            return price_details.model_dump(mode="json")

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="get_price",
            is_consequential=False,
            requires_approval=False,
            validator_cls=GetPriceInputContract,
            handler_fn=handle_get_price,
        )
        self.register_handler(
            capability_pattern="conn:pharmacy",
            operation="get_price",
            is_consequential=False,
            requires_approval=False,
            validator_cls=GetPriceInputContract,
            handler_fn=handle_get_price,
        )

        # 1d. Pharmacy: check_delivery_coverage
        def handle_check_delivery_coverage(req: ExecutionRequest) -> Dict[str, Any]:
            pincode = req.input_payload.get("pincode", "")
            med = req.input_payload.get("medicine_name")
            cov = self.pharmacy_adapter.check_delivery_coverage(pincode=pincode, medicine_name=med)
            return cov.model_dump(mode="json")

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="check_delivery_coverage",
            is_consequential=False,
            requires_approval=False,
            validator_cls=CheckDeliveryCoverageInputContract,
            handler_fn=handle_check_delivery_coverage,
        )
        self.register_handler(
            capability_pattern="conn:pharmacy",
            operation="check_delivery_coverage",
            is_consequential=False,
            requires_approval=False,
            validator_cls=CheckDeliveryCoverageInputContract,
            handler_fn=handle_check_delivery_coverage,
        )

        # 1e. Pharmacy: get_order_status
        def handle_get_order_status(req: ExecutionRequest) -> Dict[str, Any]:
            order_id = req.input_payload.get("order_id", "")
            pat_id = req.input_payload.get("patient_id")
            ord_stat = self.pharmacy_adapter.get_order_status(order_id=order_id, patient_id=pat_id)
            return ord_stat.model_dump(mode="json")

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="get_order_status",
            is_consequential=False,
            requires_approval=False,
            validator_cls=GetOrderStatusInputContract,
            handler_fn=handle_get_order_status,
        )
        self.register_handler(
            capability_pattern="conn:pharmacy",
            operation="get_order_status",
            is_consequential=False,
            requires_approval=False,
            validator_cls=GetOrderStatusInputContract,
            handler_fn=handle_get_order_status,
        )

        # 2. Pharmacy: reserve_stock (Consequential)
        def handle_reserve_stock(req: ExecutionRequest) -> Dict[str, Any]:
            res_id = f"res_{uuid.uuid4().hex[:8]}"
            return {
                "reservation_id": res_id,
                "status": "RESERVED",
                "medicine_name": req.input_payload.get("medicine_name"),
                "quantity": req.input_payload.get("quantity"),
                "patient_id": req.input_payload.get("patient_id"),
                "expires_in_hours": req.input_payload.get("reservation_hours", 24),
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="reserve_stock",
            is_consequential=True,
            requires_approval=True,
            validator_cls=ReserveStockInputContract,
            handler_fn=handle_reserve_stock,
        )

        # 3. Pharmacy: create_order (Consequential)
        def handle_create_order(req: ExecutionRequest) -> Dict[str, Any]:
            ord_id = f"ord_{uuid.uuid4().hex[:8]}"
            return {
                "order_id": ord_id,
                "status": "ORDER_PLACED_PENDING_CONFIRMATION",
                "medicine_name": req.input_payload.get("medicine_name"),
                "quantity": req.input_payload.get("quantity"),
                "patient_id": req.input_payload.get("patient_id"),
                "delivery_address": req.input_payload.get("delivery_address"),
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:apollo_pharmacy",
            operation="create_order",
            is_consequential=True,
            requires_approval=True,
            validator_cls=CreateOrderInputContract,
            handler_fn=handle_create_order,
        )

        # 4. Caregiver Tasks: create_caregiver_task (Consequential)
        def handle_create_task(req: ExecutionRequest) -> Dict[str, Any]:
            tsk_id = f"tsk_{uuid.uuid4().hex[:8]}"
            return {
                "task_id": tsk_id,
                "title": req.input_payload.get("title"),
                "patient_id": req.input_payload.get("patient_id"),
                "assigned_to": req.input_payload.get("assigned_to"),
                "priority": req.input_payload.get("priority", "NORMAL"),
                "status": "CREATED",
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:task_manager",
            operation="create_caregiver_task",
            is_consequential=True,
            requires_approval=True,
            validator_cls=CreateCaregiverTaskInputContract,
            handler_fn=handle_create_task,
        )
        self.register_handler(
            capability_pattern="mcp:create_caregiver_task",
            operation="create_caregiver_task",
            is_consequential=True,
            requires_approval=True,
            validator_cls=CreateCaregiverTaskInputContract,
            handler_fn=handle_create_task,
        )

        # 5. Caregiver Tasks: query_caregiver_task
        def handle_query_task(req: ExecutionRequest) -> Dict[str, Any]:
            return {
                "patient_id": req.input_payload.get("patient_id"),
                "tasks": [],
                "count": 0,
                "status": "ACTIVE",
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:task_manager",
            operation="query_caregiver_task",
            is_consequential=False,
            requires_approval=False,
            validator_cls=QueryCaregiverTaskInputContract,
            handler_fn=handle_query_task,
        )

        # 6. Payments: initiate_payment (Consequential)
        def handle_payment(req: ExecutionRequest) -> Dict[str, Any]:
            txn_id = f"txn_{uuid.uuid4().hex[:8]}"
            return {
                "transaction_id": txn_id,
                "order_id": req.input_payload.get("order_id"),
                "amount": req.input_payload.get("amount"),
                "currency": req.input_payload.get("currency", "INR"),
                "status": "PAYMENT_INITIATED",
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:pine_labs",
            operation="initiate_payment",
            is_consequential=True,
            requires_approval=True,
            validator_cls=InitiatePaymentInputContract,
            handler_fn=handle_payment,
        )

        # 7. Logistics: track_delivery
        def handle_track(req: ExecutionRequest) -> Dict[str, Any]:
            return {
                "tracking_number": req.input_payload.get("tracking_number"),
                "status": "IN_TRANSIT",
                "estimated_delivery": "Within 2 hours",
                "carrier": "Delhivery Express (Simulated)",
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:delhivery",
            operation="track_delivery",
            is_consequential=False,
            requires_approval=False,
            validator_cls=TrackDeliveryInputContract,
            handler_fn=handle_track,
        )

        # 8. Appointments: discover_appointment_slots
        def handle_discover_slots(req: ExecutionRequest) -> Dict[str, Any]:
            clinic_id = req.input_payload.get("clinic_id", "cln_city_01")
            p_date = req.input_payload.get("preferred_date", "2026-10-15")
            doc = req.input_payload.get("doctor_name", "Dr. Rajesh Sharma")
            slots = [
                {
                    "slot_id": f"slot_{uuid.uuid4().hex[:6]}",
                    "start_time": "10:00 AM",
                    "end_time": "10:30 AM",
                    "date": p_date,
                    "doctor_name": doc,
                    "clinic_name": "City Clinic",
                },
                {
                    "slot_id": f"slot_{uuid.uuid4().hex[:6]}",
                    "start_time": "02:30 PM",
                    "end_time": "03:00 PM",
                    "date": p_date,
                    "doctor_name": doc,
                    "clinic_name": "City Clinic",
                },
            ]
            return {
                "clinic_id": clinic_id,
                "doctor_name": doc,
                "date": p_date,
                "slots": slots,
                "count": len(slots),
                "is_simulated": True,
            }

        for cap in ["conn:clinic_coordinator", "conn:gnani_voice", "conn:apollo_clinic"]:
            self.register_handler(
                capability_pattern=cap,
                operation="discover_appointment_slots",
                is_consequential=False,
                requires_approval=False,
                validator_cls=DiscoverSlotsInputContract,
                handler_fn=handle_discover_slots,
            )

        # 9. Appointments: book_appointment (Consequential - requires HITL approval)
        def handle_book_appointment(req: ExecutionRequest) -> Dict[str, Any]:
            apt_id = req.input_payload.get("appointment_id", f"apt_{uuid.uuid4().hex[:8]}")
            slot_id = req.input_payload.get("slot_id", "slot_default")
            booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
            return {
                "appointment_id": apt_id,
                "slot_id": slot_id,
                "booking_reference": booking_ref,
                "status": "CONFIRMED",
                "clinic_id": req.input_payload.get("clinic_id"),
                "patient_id": req.input_payload.get("patient_id"),
                "is_simulated": True,
            }

        for cap in ["conn:clinic_coordinator", "conn:gnani_voice", "conn:apollo_clinic"]:
            self.register_handler(
                capability_pattern=cap,
                operation="book_appointment",
                is_consequential=True,
                requires_approval=True,
                validator_cls=BookAppointmentInputContract,
                handler_fn=handle_book_appointment,
            )

        # 10. Voice Communication: initiate_voice_call
        def handle_initiate_voice(req: ExecutionRequest) -> Dict[str, Any]:
            ext_call_id = f"gnani_call_{uuid.uuid4().hex[:8]}"
            return {
                "external_call_id": ext_call_id,
                "appointment_id": req.input_payload.get("appointment_id"),
                "status": "INITIATED",
                "clinic_phone": req.input_payload.get("clinic_phone"),
                "provider": "gnani.ai (simulated)",
                "is_simulated": True,
            }

        self.register_handler(
            capability_pattern="conn:gnani_voice",
            operation="initiate_voice_call",
            is_consequential=False,
            requires_approval=False,
            validator_cls=InitiateVoiceCallInputContract,
            handler_fn=handle_initiate_voice,
        )

    def register_handler(
        self,
        capability_pattern: str,
        operation: str,
        is_consequential: bool,
        requires_approval: bool,
        validator_cls: Optional[Type[BaseModel]] = None,
        handler_fn: Optional[Callable[[ExecutionRequest], Dict[str, Any]]] = None,
    ) -> None:
        """Register an approved execution handler."""
        reg = HandlerRegistration(
            capability_pattern=capability_pattern,
            operation=operation,
            is_consequential=is_consequential,
            requires_approval=requires_approval,
            validator_cls=validator_cls,
            handler_fn=handler_fn,
        )
        self._handlers[(capability_pattern, operation)] = reg

    def _resolve_handler(self, capability_id: str, operation: str) -> Optional[HandlerRegistration]:
        """Resolve handler by exact capability match, prefix match, or wildcard."""
        if (capability_id, operation) in self._handlers:
            return self._handlers[(capability_id, operation)]
        # Try wildcard capability pattern
        if ("*", operation) in self._handlers:
            return self._handlers[("*", operation)]
        return None

    # --------------------------------------------------------------------------
    # Central Execution Pipeline
    # --------------------------------------------------------------------------
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Process an operational tool invocation through the full policy gateway."""
        now = datetime.utcnow()
        self.audit_logger.log(
            event_type=AuditEventType.GATEWAY_EXECUTION_REQUESTED,
            status="received",
            details=f"Gateway execution requested: capability '{request.capability_id}', operation '{request.requested_operation}'",
            request_id=request.request_id,
            patient_id=request.patient_id,
            user_id=request.requesting_user_id,
            execution_mode=request.execution_mode,
            metadata={
                "capability_id": request.capability_id,
                "operation": request.requested_operation,
                "idempotency_key": request.idempotency_key,
            },
        )

        # ----------------------------------------------------------------------
        # Gate 1: Confidence Floor Check (88% Floor)
        # ----------------------------------------------------------------------
        if request.confidence_score < self.settings.agenticorg_confidence_floor:
            err = (
                f"Confidence score {request.confidence_score:.2f} is below the 88% confidence floor "
                f"({self.settings.agenticorg_confidence_floor:.2f}). Operation blocked."
            )
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.BLOCKED,
                    policy_decision=CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY,
                    error_category="CONFIDENCE_FLOOR_VIOLATION",
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )

        # ----------------------------------------------------------------------
        # Gate 2: Idempotency & Duplicate Protection Check
        # ----------------------------------------------------------------------
        if request.idempotency_key:
            cached = self._idempotency_store.get(request.idempotency_key)
            if not cached and self.idempotency_repo:
                try:
                    rec = self.idempotency_repo.get_record(request.idempotency_key)
                    if rec and self.execution_repo:
                        cached = self.execution_repo.get_execution(rec["execution_id"])
                        if cached:
                            self._idempotency_store[request.idempotency_key] = cached
                except Exception as e:
                    logger.warning("Could not query idempotency repository: %s", str(e))

            if cached:
                # If cached execution is still in-flight, protect against concurrent execution
                if cached.status in (GatewayExecutionStatus.READY, GatewayExecutionStatus.SUBMITTED):
                    err = f"Concurrent duplicate execution claim detected for idempotency key '{request.idempotency_key}'."
                    return self._record_and_return(
                        ExecutionResult(
                            request_id=request.request_id,
                            capability_id=request.capability_id,
                            operation=request.requested_operation,
                            status=GatewayExecutionStatus.REJECTED,
                            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                            error_category="CONCURRENT_IDEMPOTENCY_CLAIM",
                            error_message=err,
                            timestamp=now,
                        ),
                        request=request,
                    )
                # If prior execution was uncertain or timed out, require verification before retry
                if cached.status in (GatewayExecutionStatus.UNKNOWN_OUTCOME, GatewayExecutionStatus.TIMED_OUT):
                    err = (
                        "Prior invocation resulted in an uncertain outcome or timeout. "
                        "Reconciliation or outcome verification is strictly required before retrying."
                    )
                    return self._record_and_return(
                        ExecutionResult(
                            request_id=request.request_id,
                            capability_id=request.capability_id,
                            operation=request.requested_operation,
                            status=GatewayExecutionStatus.REQUIRES_VERIFICATION,
                            policy_decision=cached.policy_decision,
                            error_category="IDEMPOTENCY_RETRY_REQUIRES_VERIFICATION",
                            error_message=err,
                            verification_status=VerificationStatus.PENDING_VERIFICATION,
                            timestamp=now,
                        ),
                        request=request,
                    )
                # Duplicate call: return cached result with flag
                self.audit_logger.log(
                    event_type=AuditEventType.GATEWAY_IDEMPOTENCY_MATCHED,
                    status="cached",
                    details=f"Duplicate idempotency key '{request.idempotency_key}' detected. Returning cached result.",
                    request_id=request.request_id,
                    execution_mode=request.execution_mode,
                )
                duplicate_res = cached.model_copy()
                duplicate_res.idempotency_matched = True
                return duplicate_res
            elif self.idempotency_repo:
                # Atomic persistent idempotency claim
                try:
                    fingerprint = compute_parameter_hash(request.input_payload)
                    pre_exec_id = f"exec_{request.request_id}"

                    # Ensure preliminary execution placeholder exists for foreign key constraint
                    if self.execution_repo:
                        pre_result = ExecutionResult(
                            execution_id=pre_exec_id,
                            request_id=request.request_id,
                            capability_id=request.capability_id,
                            operation=request.requested_operation,
                            status=GatewayExecutionStatus.READY,
                            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                            handler_invoked=False,
                            timestamp=now,
                        )
                        self.execution_repo.save_execution(pre_result, request=request)

                    claimed = self.idempotency_repo.claim_key(
                        idempotency_key=request.idempotency_key,
                        execution_id=pre_exec_id,
                        user_id=request.requesting_user_id,
                        operation=request.requested_operation,
                        request_fingerprint=fingerprint,
                    )
                    if not claimed:
                        # Concurrent duplicate claim detected
                        err = f"Concurrent duplicate execution claim detected for idempotency key '{request.idempotency_key}'."
                        return self._record_and_return(
                            ExecutionResult(
                                request_id=request.request_id,
                                capability_id=request.capability_id,
                                operation=request.requested_operation,
                                status=GatewayExecutionStatus.REJECTED,
                                policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                                error_category="CONCURRENT_IDEMPOTENCY_CLAIM",
                                error_message=err,
                                timestamp=now,
                            ),
                            request=request,
                        )
                except Exception as e:
                    logger.error("Durable storage failure during idempotency reservation: %s", str(e))
                    err = f"Durable storage failure during idempotency reservation: {str(e)}"
                    return self._record_and_return(
                        ExecutionResult(
                            request_id=request.request_id,
                            capability_id=request.capability_id,
                            operation=request.requested_operation,
                            status=GatewayExecutionStatus.BLOCKED,
                            policy_decision=CapabilityPolicyDecision.BLOCKED_NOT_REGISTERED,
                            error_category="DATABASE_FAILURE_BLOCKED",
                            error_message=err,
                            timestamp=now,
                        ),
                        request=request,
                    )

        # ----------------------------------------------------------------------
        # Gate 3: Operation Allowlist Check (No arbitrary MCP execution)
        # ----------------------------------------------------------------------
        if request.requested_operation not in GLOBAL_OPERATION_ALLOWLIST:
            err = f"Operation '{request.requested_operation}' is not in the authorized healthcare operations allowlist."
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.REJECTED,
                    policy_decision=CapabilityPolicyDecision.BLOCKED_UNSUPPORTED_OPERATION,
                    error_category="OPERATION_NOT_ALLOWLISTED",
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )

        # ----------------------------------------------------------------------
        # Gate 4: Capability Existence & Policy Readiness Check
        # ----------------------------------------------------------------------
        cap = self.connector_registry.get_normalized_capability(request.capability_id)
        if not cap:
            err = f"Capability '{request.capability_id}' not found in normalized connector registry."
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.BLOCKED,
                    policy_decision=CapabilityPolicyDecision.BLOCKED_NOT_REGISTERED,
                    error_category="CAPABILITY_NOT_FOUND",
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )

        policy_eval = self.connector_registry.synchronizer.evaluate_capability_for_workflow(
            capability=cap,
            workflow=request.workflow_id,
            required_operation=request.requested_operation,
            healthcare_auth_context=request.authorization_context,
        )

        if policy_eval.decision != CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW:
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.BLOCKED,
                    policy_decision=policy_eval.decision,
                    error_category=policy_eval.decision.value,
                    error_message=policy_eval.reason,
                    timestamp=now,
                ),
                request=request,
            )

        # ----------------------------------------------------------------------
        # Gate 5: Handler Resolution & Input Schema Validation
        # ----------------------------------------------------------------------
        handler_reg = self._resolve_handler(request.capability_id, request.requested_operation)
        if not handler_reg:
            err = f"No approved execution handler registered for '{request.capability_id}.{request.requested_operation}'."
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.BLOCKED,
                    policy_decision=CapabilityPolicyDecision.BLOCKED_UNSUPPORTED_OPERATION,
                    error_category="NO_REGISTERED_HANDLER",
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )

        if handler_reg.validator_cls:
            try:
                handler_reg.validator_cls(**request.input_payload)
            except (ValidationError, ValueError) as ve:
                err = f"Input validation failed for operation '{request.requested_operation}': {ve}"
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INPUT_VALIDATION_ERROR",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

        # ----------------------------------------------------------------------
        # Gate 6: Healthcare Authorization Enforcement
        # ----------------------------------------------------------------------
        # If operation relates to a patient, patient_id must be provided
        requires_patient = any(
            t in request.requested_operation
            for t in ["inventory", "order", "task", "payment", "medicine", "prescription"]
        )
        if requires_patient and not request.patient_id:
            err = f"Operation '{request.requested_operation}' requires an explicit patient reference."
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.REJECTED,
                    policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                    error_category="MISSING_PATIENT_SCOPE",
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )

        if request.patient_id:
            is_auth, auth_reason = self.policy_engine.authorize_request(
                user_id=request.requesting_user_id,
                patient_id=request.patient_id,
                action=request.requested_operation,
                parameters=request.input_payload,
            )
            if not is_auth:
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.BLOCKED_UNAUTHORIZED,
                        error_category="HEALTHCARE_AUTHORIZATION_DENIED",
                        error_message=auth_reason,
                        timestamp=now,
                    ),
                    request=request,
                )

        # ----------------------------------------------------------------------
        # Gate 7: Human-in-the-Loop (HITL) Approval Check
        # ----------------------------------------------------------------------
        is_consequential = handler_reg.is_consequential or self.policy_engine.is_consequential_action(
            request.requested_operation
        )

        if is_consequential:
            if not request.approval_id:
                err = f"Consequential operation '{request.requested_operation}' requires explicit human approval."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.PENDING_APPROVAL,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="APPROVAL_REQUIRED",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

            # Validate approval record
            approval_rec = self.approval_manager._approvals.get(request.approval_id)
            if not approval_rec:
                err = f"Approval record '{request.approval_id}' not found."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INVALID_APPROVAL",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

            if approval_rec.approval_status != ApprovalStatus.GRANTED:
                err = f"Approval '{request.approval_id}' is not in GRANTED state (current: {approval_rec.approval_status.value})."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INVALID_APPROVAL",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

            if approval_rec.user_identity != request.requesting_user_id:
                err = f"Approval '{request.approval_id}' was granted for user '{approval_rec.user_identity}', not '{request.requesting_user_id}'."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INVALID_APPROVAL",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

            # 1. Check operation type match
            act_val = (
                approval_rec.action_being_approved.value
                if hasattr(approval_rec.action_being_approved, "value")
                else str(approval_rec.action_being_approved)
            )
            matching = (act_val == request.requested_operation) or (
                act_val == "place_medicine_order" and request.requested_operation in ("create_order", "place_medicine_order")
            ) or (
                act_val == "create_caregiver_task" and request.requested_operation in ("create_caregiver_task", "create_task")
            ) or (
                act_val == "initiate_payment" and request.requested_operation in ("initiate_payment", "pay")
            )
            if not matching:
                err = f"Approval granted for action '{act_val}' does not authorize requested operation '{request.requested_operation}'."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INVALID_APPROVAL",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

            # 2. Check expiration
            if datetime.utcnow() > approval_rec.expiration:
                err = "Approval has expired. A fresh approval is required."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INVALID_APPROVAL",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

            # 3. Check parameter hash binding
            current_hash = compute_parameter_hash(request.input_payload)
            if current_hash != approval_rec.parameter_hash:
                err = "Operation input parameters have been modified since approval was granted. Approval revoked."
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.REJECTED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        error_category="INVALID_APPROVAL",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

        # ----------------------------------------------------------------------
        # Gate 8: Execution Mode Policy
        # ----------------------------------------------------------------------
        # 1. Live Execution Check (Disabled by default in Module 9)
        if request.execution_mode == ExecutionMode.AUTHORIZED_EXECUTION:
            if not self.settings.live_execution_enabled:
                err = (
                    "Live external operation execution is disabled by policy in Module 9. "
                    "Only registered simulation handlers are permitted."
                )
                return self._record_and_return(
                    ExecutionResult(
                        request_id=request.request_id,
                        capability_id=request.capability_id,
                        operation=request.requested_operation,
                        status=GatewayExecutionStatus.BLOCKED,
                        policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                        handler_invoked=False,
                        error_category="LIVE_EXECUTION_DISABLED",
                        error_message=err,
                        timestamp=now,
                    ),
                    request=request,
                )

        # 2. Shadow Mode Check: CONNECTED_READ_ONLY or shadow deployment in live mode
        is_shadow = request.execution_mode == ExecutionMode.CONNECTED_READ_ONLY
        if is_shadow:
            shadow_out = {
                "shadow_mode": True,
                "evaluated_operation": request.requested_operation,
                "capability_id": request.capability_id,
                "message": "Shadow mode active: operational invocation withheld by policy.",
            }
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.READY,
                    policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                    handler_invoked=False,
                    is_simulated=True,
                    output=shadow_out,
                    timestamp=now,
                ),
                request=request,
            )

        # ----------------------------------------------------------------------
        # Gate 9: Controlled Handler Invocation
        # ----------------------------------------------------------------------
        try:
            handler_output = handler_reg.handler_fn(request)
        except PharmacyAdapterException as pae:
            err = f"Pharmacy provider error: {pae.details}"
            if pae.category == PharmacyErrorCategory.TIMEOUT:
                status = GatewayExecutionStatus.TIMED_OUT
            elif pae.category in (
                PharmacyErrorCategory.AUTHENTICATION_FAILURE,
                PharmacyErrorCategory.AUTHORIZATION_FAILURE,
                PharmacyErrorCategory.UNVERIFIED_PROVIDER,
            ):
                status = GatewayExecutionStatus.REJECTED
            elif pae.category == PharmacyErrorCategory.LIVE_ORDERING_DISABLED:
                status = GatewayExecutionStatus.BLOCKED
            else:
                status = GatewayExecutionStatus.FAILED

            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=status,
                    policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                    handler_invoked=True,
                    error_category=pae.category.value,
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )
        except TimeoutError as te:
            err = f"Execution timed out during handler invocation: {te}"
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.TIMED_OUT,
                    policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                    handler_invoked=True,
                    error_category="HANDLER_TIMEOUT",
                    error_message=err,
                    verification_status=VerificationStatus.PENDING_VERIFICATION,
                    timestamp=now,
                ),
                request=request,
            )
        except Exception as e:
            err = f"Handler execution error: {e}"
            return self._record_and_return(
                ExecutionResult(
                    request_id=request.request_id,
                    capability_id=request.capability_id,
                    operation=request.requested_operation,
                    status=GatewayExecutionStatus.FAILED,
                    policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
                    handler_invoked=True,
                    error_category="HANDLER_ERROR",
                    error_message=err,
                    timestamp=now,
                ),
                request=request,
            )

        # ----------------------------------------------------------------------
        # Gate 10: Outcome Verification Integration
        # ----------------------------------------------------------------------
        # Consequential delivery/order actions are marked PENDING_VERIFICATION
        is_delivery_or_clinical = any(w in request.requested_operation for w in ["order", "delivery", "dispense"])
        verif_status = (
            VerificationStatus.PENDING_VERIFICATION
            if is_delivery_or_clinical
            else VerificationStatus.NOT_APPLICABLE
        )

        exec_res = ExecutionResult(
            request_id=request.request_id,
            capability_id=request.capability_id,
            operation=request.requested_operation,
            status=GatewayExecutionStatus.SIMULATED,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
            handler_invoked=True,
            is_simulated=True,
            output=handler_output,
            verification_status=verif_status,
            timestamp=now,
        )

        # Register in Outcome Verification Service
        rec = self.verification_service.create_execution_record(
            request_id=request.request_id,
            operation_type=request.requested_operation,
            status="simulated",
        )
        self.verification_service.record_execution_success(
            operation_id=rec.operation_id,
            provider_response=handler_output,
            evidence_description="Simulated execution handler response",
            evidence_source=request.capability_id,
            is_delivery_or_clinical=is_delivery_or_clinical,
        )

        return self._record_and_return(exec_res, request=request)

    def _record_and_return(self, result: ExecutionResult, request: ExecutionRequest) -> ExecutionResult:
        """Cache idempotency, store history, and audit log."""
        if request:
            # Ensure deterministic execution_id consistency between preliminary claim and final record
            result.execution_id = f"exec_{request.request_id}"
        if request.idempotency_key:
            self._idempotency_store[request.idempotency_key] = result
            if self.idempotency_repo:
                try:
                    self.idempotency_repo.update_status(request.idempotency_key, result.status.value)
                except Exception as e:
                    logger.error("Failed to update idempotency status in repository: %s", str(e))

        self._execution_history.append(result)
        if self.execution_repo:
            try:
                self.execution_repo.save_execution(result, request=request)
            except Exception as e:
                logger.error("Failed to persist execution result in repository: %s", str(e))

        event_map = {
            GatewayExecutionStatus.BLOCKED: AuditEventType.GATEWAY_EXECUTION_BLOCKED,
            GatewayExecutionStatus.REJECTED: AuditEventType.GATEWAY_EXECUTION_REJECTED,
            GatewayExecutionStatus.SIMULATED: AuditEventType.GATEWAY_EXECUTION_SIMULATED,
            GatewayExecutionStatus.SUCCEEDED: AuditEventType.GATEWAY_EXECUTION_SUCCEEDED,
            GatewayExecutionStatus.FAILED: AuditEventType.GATEWAY_EXECUTION_FAILED,
            GatewayExecutionStatus.TIMED_OUT: AuditEventType.GATEWAY_EXECUTION_TIMEOUT,
            GatewayExecutionStatus.REQUIRES_VERIFICATION: AuditEventType.GATEWAY_VERIFICATION_REQUIRED,
        }
        event_type = event_map.get(result.status, AuditEventType.OPERATION_EXECUTED)

        # Sanitize metadata before audit logging
        clean_out = None
        if result.output:
            clean_out = {
                k: v for k, v in result.output.items()
                if not any(s in k.lower() for s in ["key", "token", "secret", "auth", "password"])
            }

        self.audit_logger.log(
            event_type=event_type,
            status=result.status.value,
            details=f"Gateway result: status={result.status.value}, error={result.error_category or 'none'}",
            request_id=request.request_id,
            patient_id=request.patient_id,
            user_id=request.requesting_user_id,
            execution_mode=request.execution_mode,
            metadata={
                "execution_id": result.execution_id,
                "status": result.status.value,
                "policy_decision": result.policy_decision.value,
                "error_category": result.error_category,
                "is_simulated": result.is_simulated,
                "handler_invoked": result.handler_invoked,
            },
        )
        return result
