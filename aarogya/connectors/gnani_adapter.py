"""Gnani.ai Voice Provider Interface and Mock Adapter for Clinic Coordination."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from ..models.appointment import AppointmentSlot
from ..models.voice import (
    VoiceCallRequest,
    VoiceCallOutcomeEvent,
    VoiceCallRecord,
)
from ..models.enums import VoiceCallStatus, VoiceCallDisposition

logger = logging.getLogger(__name__)


class VoiceCallResult(BaseModel):
    """Normalized response from a voice coordination call session."""
    external_call_id: str
    appointment_id: str
    status: VoiceCallStatus
    disposition: VoiceCallDisposition
    available_slots: List[AppointmentSlot] = Field(default_factory=list)
    selected_slot: Optional[AppointmentSlot] = None
    booking_confirmed: bool = False
    booking_reference: Optional[str] = None
    failure_reason: Optional[str] = None
    callback_required: bool = False
    is_simulated: bool = True
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceProviderInterface(ABC):
    """Abstract interface for external voice communication providers (e.g. Gnani.ai)."""

    @abstractmethod
    def initiate_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Initiate an outbound clinic coordination call."""
        pass

    @abstractmethod
    def get_call_status(self, external_call_id: str) -> Optional[VoiceCallResult]:
        """Poll or inspect status of an active voice call."""
        pass

    @abstractmethod
    def process_webhook_outcome(self, outcome: VoiceCallOutcomeEvent) -> VoiceCallResult:
        """Process a structured callback/outcome from the voice agent."""
        pass


class MockGnaniVoiceProvider(VoiceProviderInterface):
    """Mock implementation of Gnani.ai voice coordination provider.
    
    Provides deterministic simulation scenarios:
    - availability_found_preferred (preferred slot available)
    - preferred_unavailable_alternatives (alternative slots returned, requiring HITL approval)
    - no_slots_available
    - booking_confirmed
    - booking_failed
    - call_dropped
    - unknown_outcome
    """

    def __init__(self, default_scenario: str = "preferred_unavailable_alternatives"):
        self.default_scenario = default_scenario
        self._calls: Dict[str, VoiceCallResult] = {}
        self._call_scenarios: Dict[str, str] = {}

    def set_scenario(self, scenario: str, call_id: Optional[str] = None) -> None:
        """Configure simulation scenario globally or for a specific call."""
        if call_id:
            self._call_scenarios[call_id] = scenario
        else:
            self.default_scenario = scenario

    def initiate_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Simulate initiating an outbound voice call to clinic."""
        external_call_id = f"gnani_{uuid.uuid4().hex[:10]}"
        scenario = request.metadata.get("simulation_scenario") or self._call_scenarios.get(
            request.appointment_id, self.default_scenario
        )

        p_date = request.preferred_date
        p_time = request.preferred_time or "10:00 AM"

        if scenario == "availability_found_preferred":
            # Preferred slot matches
            preferred_slot = AppointmentSlot(
                slot_id=f"slot_pref_{uuid.uuid4().hex[:6]}",
                date=p_date,
                start_time=p_time,
                end_time="10:30 AM",
                doctor_name=request.doctor_name or "Dr. Rajesh Sharma",
                clinic_name=request.clinic_name,
            )
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.COMPLETED,
                disposition=VoiceCallDisposition.SLOTS_OFFERED,
                available_slots=[preferred_slot],
                selected_slot=preferred_slot,
                booking_confirmed=False,
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        elif scenario == "preferred_unavailable_alternatives":
            # Preferred is not available; clinic offers 2 alternative slots
            alt1 = AppointmentSlot(
                slot_id=f"slot_alt_{uuid.uuid4().hex[:6]}",
                date=p_date,
                start_time="02:30 PM",
                end_time="03:00 PM",
                doctor_name=request.doctor_name or "Dr. Rajesh Sharma",
                clinic_name=request.clinic_name,
                notes="Afternoon alternative",
            )
            alt2 = AppointmentSlot(
                slot_id=f"slot_alt_{uuid.uuid4().hex[:6]}",
                date=p_date,
                start_time="04:30 PM",
                end_time="05:00 PM",
                doctor_name=request.doctor_name or "Dr. Rajesh Sharma",
                clinic_name=request.clinic_name,
                notes="Evening alternative",
            )
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.COMPLETED,
                disposition=VoiceCallDisposition.SLOTS_OFFERED,
                available_slots=[alt1, alt2],
                selected_slot=None,  # Not auto-selected! Requires patient/caregiver approval
                booking_confirmed=False,
                is_simulated=True,
                raw_metadata={"scenario": scenario, "unavailability_reason": "Morning slot full"},
            )

        elif scenario == "no_slots_available":
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.COMPLETED,
                disposition=VoiceCallDisposition.NO_SLOTS_AVAILABLE,
                available_slots=[],
                failure_reason="No consultation slots available for selected date.",
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        elif scenario == "call_dropped":
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.DROPPED,
                disposition=VoiceCallDisposition.CALL_DISCONNECTED,
                available_slots=[],
                failure_reason="Clinic phone call dropped or disconnected prematurely before confirmation.",
                callback_required=True,
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        elif scenario == "unknown_outcome":
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.UNKNOWN,
                disposition=VoiceCallDisposition.UNKNOWN,
                available_slots=[],
                failure_reason="Reception desk put on hold; line timed out without slot confirmation.",
                callback_required=True,
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        elif scenario == "booking_confirmed":
            confirmed_slot = AppointmentSlot(
                slot_id=f"slot_cnf_{uuid.uuid4().hex[:6]}",
                date=p_date,
                start_time=p_time,
                doctor_name=request.doctor_name or "Dr. Rajesh Sharma",
                clinic_name=request.clinic_name,
            )
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.COMPLETED,
                disposition=VoiceCallDisposition.BOOKING_CONFIRMED,
                available_slots=[confirmed_slot],
                selected_slot=confirmed_slot,
                booking_confirmed=True,
                booking_reference=f"BK-GNANI-{uuid.uuid4().hex[:6].upper()}",
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        elif scenario == "booking_failed":
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.FAILED,
                disposition=VoiceCallDisposition.BOOKING_REJECTED,
                available_slots=[],
                booking_confirmed=False,
                failure_reason="Requested slot was taken by another walk-in patient.",
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        else:
            result = VoiceCallResult(
                external_call_id=external_call_id,
                appointment_id=request.appointment_id,
                status=VoiceCallStatus.INITIATED,
                disposition=VoiceCallDisposition.UNKNOWN,
                is_simulated=True,
                raw_metadata={"scenario": scenario},
            )

        self._calls[external_call_id] = result
        return result

    def get_call_status(self, external_call_id: str) -> Optional[VoiceCallResult]:
        return self._calls.get(external_call_id)

    def process_webhook_outcome(self, outcome: VoiceCallOutcomeEvent) -> VoiceCallResult:
        """Process structured callback from voice agent."""
        result = VoiceCallResult(
            external_call_id=outcome.external_call_id,
            appointment_id=outcome.appointment_id,
            status=outcome.status,
            disposition=outcome.disposition,
            available_slots=outcome.available_slots,
            selected_slot=outcome.selected_slot,
            booking_confirmed=outcome.booking_confirmed,
            booking_reference=outcome.booking_reference,
            failure_reason=outcome.failure_reason,
            callback_required=outcome.callback_required,
            is_simulated=True,
            raw_metadata=outcome.metadata,
        )
        self._calls[outcome.external_call_id] = result
        return result
