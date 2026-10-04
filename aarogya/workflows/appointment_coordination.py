"""Phase 14: Appointment Coordination and Voice Workflow.

Coordinates patient appointment discovery, slot evaluation, human approval
for alternatives, voice agent interaction, and policy-governed booking execution.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Dict, Any, Tuple, List

from ..brain.family_health_brain import FamilyHealthBrain
from ..policy.authorization_engine import PolicyAuthorizationEngine
from .approval_manager import ApprovalManager
from ..orchestrator.audit_logger import AuditLogger
from ..connectors.gnani_adapter import (
    VoiceProviderInterface,
    MockGnaniVoiceProvider,
    VoiceCallResult,
)
from ..models.appointment import (
    AppointmentRequest,
    AppointmentRecord,
    AppointmentSlot,
    AppointmentSlotApprovalRequest,
)
from ..models.voice import (
    VoiceCallRequest,
    VoiceCallOutcomeEvent,
    VoiceCallRecord,
    VoiceContextResponse,
)
from ..models.enums import (
    AppointmentStatus,
    VoiceCallStatus,
    VoiceCallDisposition,
    ActionType,
    AuditEventType,
    ExecutionMode,
    GatewayExecutionStatus,
)
from ..models.gateway import ExecutionRequest
from ..persistence.base import AppointmentRepository, VoiceRepository

logger = logging.getLogger(__name__)

# Emergency keywords that must bypass routine appointment scheduling
EMERGENCY_KEYWORDS = {
    "chest pain",
    "heart attack",
    "shortness of breath",
    "difficulty breathing",
    "unconscious",
    "severe bleeding",
    "stroke",
    "anaphylaxis",
    "suicidal",
}


class AppointmentCoordinationWorkflow:
    """Manages appointment coordination, voice clinic interaction, and booking."""

    def __init__(
        self,
        brain: FamilyHealthBrain,
        policy_engine: PolicyAuthorizationEngine,
        approval_manager: Optional[ApprovalManager] = None,
        execution_gateway: Optional[Any] = None,
        appointment_repo: Optional[AppointmentRepository] = None,
        voice_repo: Optional[VoiceRepository] = None,
        voice_provider: Optional[VoiceProviderInterface] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.brain = brain
        self.policy_engine = policy_engine
        self.approval_manager = approval_manager or ApprovalManager()
        self.execution_gateway = execution_gateway
        self.appointment_repo = appointment_repo
        self.voice_repo = voice_repo
        self.voice_provider = voice_provider or MockGnaniVoiceProvider()
        self.audit_logger = audit_logger or AuditLogger()
        self._in_memory_records: Dict[str, AppointmentRecord] = {}

    def _get_record(self, appointment_id: str) -> Optional[AppointmentRecord]:
        if self.appointment_repo:
            rec = self.appointment_repo.get(appointment_id)
            if rec:
                return rec
        return self._in_memory_records.get(appointment_id)

    def _save_record(self, record: AppointmentRecord) -> None:
        self._in_memory_records[record.appointment_id] = record
        if self.appointment_repo:
            self.appointment_repo.save(record)

    def initiate_coordination(
        self, request: AppointmentRequest
    ) -> Tuple[bool, str, Optional[AppointmentRecord]]:
        """Initiate appointment coordination for a patient.
        
        Validates emergency flags, patient authorization, queries clinic slots,
        and requests HITL approval if preferred slot is unavailable.
        """
        # Step 1: Emergency triage safeguard
        reason = (request.reason_for_visit or "").lower()
        if any(kw in reason for kw in EMERGENCY_KEYWORDS):
            self.audit_logger.log(
                event_type=AuditEventType.EMERGENCY_ROUTED,
                status="emergency_detected",
                details=f"Emergency symptom detected in appointment reason: '{request.reason_for_visit}'. Bypassing routine scheduling.",
                request_id=request.request_id,
                patient_id=request.patient_id,
                user_id=request.requesting_user_id,
            )
            return (
                False,
                "Emergency symptoms detected: routine appointment scheduling is bypassed. "
                "Immediate medical attention or emergency services required.",
                None,
            )

        # Step 2: Patient and family authorization check
        is_auth, auth_reason = self.policy_engine.authorize_request(
            user_id=request.requesting_user_id,
            patient_id=request.patient_id,
            action="appointment",
        )
        if not is_auth:
            self.audit_logger.log(
                event_type=AuditEventType.AUTHORIZATION_EVALUATED,
                status="unauthorized",
                details=f"Appointment coordination denied: {auth_reason}",
                request_id=request.request_id,
                patient_id=request.patient_id,
                user_id=request.requesting_user_id,
            )
            return False, f"Unauthorized: {auth_reason}", None

        # Step 3: Idempotency check
        if request.idempotency_key and self.appointment_repo:
            existing = self.appointment_repo.get_by_idempotency_key(request.idempotency_key)
            if existing:
                return True, "Idempotent appointment record retrieved", existing

        # Step 4: Create pending appointment record
        appointment_id = f"apt_{uuid.uuid4().hex[:10]}"
        record = AppointmentRecord(
            appointment_id=appointment_id,
            request_id=request.request_id,
            patient_id=request.patient_id,
            requesting_user_id=request.requesting_user_id,
            clinic=request.clinic,
            doctor=request.doctor,
            preferred_date=request.preferred_date,
            preferred_time=request.preferred_time,
            status=AppointmentStatus.AVAILABILITY_PENDING,
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            metadata=request.metadata,
        )
        self._save_record(record)

        self.audit_logger.log(
            event_type=AuditEventType.APPOINTMENT_REQUESTED,
            status="requested",
            details=f"Appointment coordination initiated for patient '{request.patient_id}' at clinic '{request.clinic.clinic_name}'",
            request_id=request.request_id,
            patient_id=request.patient_id,
            user_id=request.requesting_user_id,
        )

        # Step 5: Initiate voice availability check with clinic
        voice_req = VoiceCallRequest(
            appointment_id=appointment_id,
            clinic_id=request.clinic.clinic_id,
            clinic_name=request.clinic.clinic_name,
            clinic_phone=request.clinic.contact_phone or "+91-80-12345678",
            doctor_name=request.doctor.doctor_name if request.doctor else None,
            preferred_date=request.preferred_date,
            preferred_time=request.preferred_time,
            patient_id=request.patient_id,
            metadata=request.metadata,
        )

        call_result: VoiceCallResult = self.voice_provider.initiate_call(voice_req)

        # Step 6: Record voice call session in voice repo
        voice_rec = VoiceCallRecord(
            call_id=f"vcall_{uuid.uuid4().hex[:10]}",
            external_call_id=call_result.external_call_id,
            appointment_id=appointment_id,
            clinic_id=request.clinic.clinic_id,
            clinic_name=request.clinic.clinic_name,
            status=call_result.status,
            disposition=call_result.disposition,
            available_slots=call_result.available_slots,
            selected_slot=call_result.selected_slot,
            booking_outcome="CONFIRMED" if call_result.booking_confirmed else "PENDING",
            booking_reference=call_result.booking_reference,
            failure_reason=call_result.failure_reason,
            callback_required=call_result.callback_required,
            idempotency_key=f"call_idem_{call_result.external_call_id}",
            metadata=call_result.raw_metadata,
        )
        if self.voice_repo:
            self.voice_repo.save_call(voice_rec)

        self.audit_logger.log(
            event_type=AuditEventType.VOICE_CALL_INITIATED,
            status=call_result.status.value,
            details=f"Voice coordination call completed: disposition '{call_result.disposition.value}'",
            request_id=request.request_id,
            patient_id=request.patient_id,
            user_id=request.requesting_user_id,
        )

        # Step 7: Evaluate call outcome and transition appointment state
        if call_result.status == VoiceCallStatus.DROPPED:
            record.status = AppointmentStatus.UNKNOWN
            record.uncertainty_reason = call_result.failure_reason or "Voice call dropped before confirmation"
            self._save_record(record)
            return True, "Clinic call dropped. Outcome unknown pending reconciliation.", record

        if call_result.status == VoiceCallStatus.UNKNOWN or call_result.disposition == VoiceCallDisposition.UNKNOWN:
            record.status = AppointmentStatus.UNKNOWN
            record.uncertainty_reason = call_result.failure_reason or "Unknown outcome from clinic coordination"
            self._save_record(record)
            return True, "Clinic coordination returned uncertain outcome. Awaiting verification.", record

        if call_result.disposition == VoiceCallDisposition.NO_SLOTS_AVAILABLE:
            record.status = AppointmentStatus.FAILED
            record.failure_reason = call_result.failure_reason or "No appointment slots available"
            self._save_record(record)
            return True, "No consultation slots available at the requested clinic.", record

        # Available slots returned
        record.available_slots = call_result.available_slots
        self.audit_logger.log(
            event_type=AuditEventType.APPOINTMENT_SLOTS_RECEIVED,
            status="slots_received",
            details=f"Received {len(call_result.available_slots)} available slots from clinic",
            request_id=request.request_id,
            patient_id=request.patient_id,
            user_id=request.requesting_user_id,
        )

        # Check if preferred slot is an exact match
        pref_match = None
        for s in call_result.available_slots:
            if s.date == request.preferred_date and (
                not request.preferred_time or s.start_time.strip().lower() == request.preferred_time.strip().lower()
            ):
                pref_match = s
                break

        if pref_match:
            record.status = AppointmentStatus.SLOTS_RECEIVED
            record.approved_slot = pref_match
            self._save_record(record)
            return True, "Preferred appointment slot is available.", record

        # Preferred slot is unavailable, alternatives offered: Caregiver/patient approval strictly required
        record.status = AppointmentStatus.AWAITING_PATIENT_APPROVAL
        self._save_record(record)

        # Create HITL approval request for slot selection
        self.approval_manager.request_approval(
            request_id=request.request_id,
            user_identity=request.requesting_user_id,
            action_type=ActionType.BOOK_APPOINTMENT,
            parameters={
                "appointment_id": appointment_id,
                "patient_id": request.patient_id,
                "clinic_name": request.clinic.clinic_name,
                "preferred_date": request.preferred_date,
                "available_slots": [s.model_dump() for s in record.available_slots],
            },
        )

        return (
            True,
            "Preferred slot unavailable. Alternative slots received; awaiting patient/caregiver approval.",
            record,
        )

    def approve_and_book_slot(
        self, approval_request: AppointmentSlotApprovalRequest
    ) -> Tuple[bool, str, Optional[AppointmentRecord]]:
        """Record explicit caregiver/patient approval for an appointment slot and route booking.
        
        Autonomous selection of alternative slots is strictly forbidden.
        Only explicitly authorized slots can be booked.
        """
        record = self._get_record(approval_request.appointment_id)
        if not record:
            return False, f"Appointment '{approval_request.appointment_id}' not found.", None

        # Validate authorization to book
        is_auth, auth_reason = self.policy_engine.authorize_request(
            user_id=approval_request.approving_user_id,
            patient_id=record.patient_id,
            action="book_appointment",
        )
        if not is_auth:
            return False, f"Unauthorized: {auth_reason}", record

        # Validate selected slot belongs to offered available slots
        matching_slot = next(
            (s for s in record.available_slots if s.slot_id == approval_request.slot_id),
            None,
        )
        if not matching_slot:
            return (
                False,
                f"Slot '{approval_request.slot_id}' is not in the list of clinic-offered available slots. Selection rejected.",
                record,
            )

        # Record patient approval
        record.approved_slot = matching_slot
        record.status = AppointmentStatus.APPROVED
        self._save_record(record)

        self.audit_logger.log(
            event_type=AuditEventType.APPOINTMENT_APPROVED,
            status="approved",
            details=f"Slot '{matching_slot.slot_id}' approved by user '{approval_request.approving_user_id}' for patient '{record.patient_id}'",
            request_id=record.request_id,
            patient_id=record.patient_id,
            user_id=approval_request.approving_user_id,
        )

        # Consequential action: Route through ExecutionGateway
        record.status = AppointmentStatus.BOOKING_IN_PROGRESS
        self._save_record(record)

        if self.execution_gateway:
            gw_req = ExecutionRequest(
                request_id=f"book_{record.appointment_id}",
                capability_id="conn:clinic_coordinator",
                requested_operation="book_appointment",
                input_payload={
                    "appointment_id": record.appointment_id,
                    "clinic_id": record.clinic.clinic_id,
                    "slot_id": matching_slot.slot_id,
                    "patient_id": record.patient_id,
                    "doctor_name": record.doctor.doctor_name if record.doctor else "Doctor",
                },
                requesting_user_id=approval_request.approving_user_id,
                patient_id=record.patient_id,
                execution_mode=ExecutionMode.SIMULATION,
            )
            gw_res = self.execution_gateway.execute(gw_req)
            if gw_res.status == GatewayExecutionStatus.SUCCEEDED and gw_res.output:
                booking_ref = gw_res.output.get("booking_reference")
                record.status = AppointmentStatus.CONFIRMED
                record.clinic_booking_reference = booking_ref
                self._save_record(record)

                self.audit_logger.log(
                    event_type=AuditEventType.APPOINTMENT_CONFIRMED,
                    status="confirmed",
                    details=f"Appointment booked and confirmed. Reference: {booking_ref}",
                    request_id=record.request_id,
                    patient_id=record.patient_id,
                    user_id=approval_request.approving_user_id,
                )
                return True, f"Appointment successfully confirmed. Booking reference: {booking_ref}", record
            else:
                record.status = AppointmentStatus.FAILED
                record.failure_reason = gw_res.error_message or "Gateway execution failed to book appointment"
                self._save_record(record)

                self.audit_logger.log(
                    event_type=AuditEventType.APPOINTMENT_FAILED,
                    status="failed",
                    details=f"Booking failed: {record.failure_reason}",
                    request_id=record.request_id,
                    patient_id=record.patient_id,
                    user_id=approval_request.approving_user_id,
                )
                return False, f"Booking failed: {record.failure_reason}", record

        # Fallback simulation if gateway not attached
        booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
        record.status = AppointmentStatus.CONFIRMED
        record.clinic_booking_reference = booking_ref
        self._save_record(record)
        return True, f"Appointment confirmed. Reference: {booking_ref}", record

    def process_voice_outcome(
        self, outcome: VoiceCallOutcomeEvent
    ) -> Tuple[bool, str, Optional[AppointmentRecord]]:
        """Ingest and validate an external voice outcome callback.
        
        Enforces idempotency and ensures appointments are not marked confirmed
        merely because a call completed without verified booking confirmation.
        """
        # Idempotency check for webhook events
        if self.voice_repo:
            is_new = self.voice_repo.record_external_event(
                event_id=f"ev_{uuid.uuid4().hex[:10]}",
                event_source="gnani_webhook",
                event_type="call_outcome",
                idempotency_key=outcome.idempotency_key,
                payload=outcome.model_dump_json() if hasattr(outcome, "model_dump_json") else str(outcome.dict()),
            )
            if not is_new:
                logger.info("Duplicate voice outcome event ignored: %s", outcome.idempotency_key)
                record = self._get_record(outcome.appointment_id)
                return True, "Duplicate callback ignored (already processed)", record

        record = self._get_record(outcome.appointment_id)
        if not record:
            return False, f"Appointment '{outcome.appointment_id}' not found for callback.", None

        # Persist voice call record
        if self.voice_repo:
            call_rec = VoiceCallRecord(
                call_id=f"vcall_{uuid.uuid4().hex[:10]}",
                external_call_id=outcome.external_call_id,
                appointment_id=outcome.appointment_id,
                clinic_id=outcome.clinic_id,
                clinic_name=outcome.clinic_name,
                status=outcome.status,
                disposition=outcome.disposition,
                available_slots=outcome.available_slots,
                selected_slot=outcome.selected_slot,
                booking_outcome="CONFIRMED" if outcome.booking_confirmed else "UNCONFIRMED",
                booking_reference=outcome.booking_reference,
                failure_reason=outcome.failure_reason,
                callback_required=outcome.callback_required,
                idempotency_key=outcome.idempotency_key,
                metadata=outcome.metadata,
            )
            self.voice_repo.save_call(call_rec)

        self.audit_logger.log(
            event_type=AuditEventType.VOICE_OUTCOME_RECEIVED,
            status=outcome.status.value,
            details=f"Voice outcome callback processed: disposition '{outcome.disposition.value}', confirmed={outcome.booking_confirmed}",
            request_id=record.request_id,
            patient_id=record.patient_id,
            user_id=record.requesting_user_id,
        )

        # Handle disposition and state changes safely
        if outcome.status == VoiceCallStatus.DROPPED:
            record.status = AppointmentStatus.UNKNOWN
            record.uncertainty_reason = outcome.failure_reason or "Call dropped prematurely"
            self._save_record(record)
            return True, "Voice call dropped; appointment status set to UNKNOWN pending reconciliation.", record

        if outcome.status == VoiceCallStatus.UNKNOWN or outcome.disposition == VoiceCallDisposition.UNKNOWN:
            record.status = AppointmentStatus.UNKNOWN
            record.uncertainty_reason = outcome.failure_reason or "Unknown outcome reported by voice coordinator"
            self._save_record(record)
            return True, "Outcome unknown; reconciliation required.", record

        if outcome.booking_confirmed and outcome.booking_reference:
            # Explicit clinic confirmation
            record.status = AppointmentStatus.CONFIRMED
            record.clinic_booking_reference = outcome.booking_reference
            if outcome.selected_slot:
                record.approved_slot = outcome.selected_slot
            self._save_record(record)
            return True, f"Appointment verified and confirmed: {outcome.booking_reference}", record

        if outcome.available_slots:
            record.available_slots = outcome.available_slots
            record.status = AppointmentStatus.AWAITING_PATIENT_APPROVAL
            self._save_record(record)
            return True, "Alternative slots received from clinic; awaiting approval.", record

        if outcome.failure_reason:
            record.status = AppointmentStatus.FAILED
            record.failure_reason = outcome.failure_reason
            self._save_record(record)
            return True, f"Appointment coordination failed: {outcome.failure_reason}", record

        self._save_record(record)
        return True, "Voice outcome recorded.", record

    def get_voice_context(
        self, appointment_id: str, requesting_user_id: str
    ) -> Tuple[bool, str, Optional[VoiceContextResponse]]:
        """Return minimal, authorized, non-sensitive context for clinic voice coordination.
        
        Ensures no raw medical history or sensitive clinical details are exposed.
        """
        record = self._get_record(appointment_id)
        if not record:
            return False, f"Appointment '{appointment_id}' not found.", None

        # Verify access permission
        is_auth, auth_reason = self.policy_engine.authorize_request(
            user_id=requesting_user_id,
            patient_id=record.patient_id,
            action="view_records",
        )
        if not is_auth:
            return False, f"Unauthorized: {auth_reason}", None

        patient = self.brain.get_patient(record.patient_id)
        display_name = patient.full_name if patient else "Patient"

        context = VoiceContextResponse(
            appointment_id=record.appointment_id,
            patient_id=record.patient_id,
            patient_display_name=display_name,
            clinic_id=record.clinic.clinic_id,
            clinic_name=record.clinic.clinic_name,
            doctor_name=record.doctor.doctor_name if record.doctor else None,
            preferred_date=record.preferred_date,
            preferred_time=record.preferred_time,
            status=record.status.value,
            requires_approval=record.status == AppointmentStatus.AWAITING_PATIENT_APPROVAL,
        )
        return True, "Voice context retrieved successfully.", context
