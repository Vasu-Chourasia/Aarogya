"""Domain models for Voice Coordination and Integration."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import uuid
from pydantic import BaseModel, Field

from .enums import VoiceCallStatus, VoiceCallDisposition
from .appointment import AppointmentSlot


class VoiceCallRequest(BaseModel):
    """Payload to initiate a voice call to a clinic."""
    appointment_id: str
    clinic_id: str
    clinic_name: str
    clinic_phone: str
    doctor_name: Optional[str] = None
    preferred_date: str
    preferred_time: Optional[str] = None
    patient_id: str
    patient_alias: Optional[str] = None
    idempotency_key: Optional[str] = Field(default_factory=lambda: f"vck_{uuid.uuid4().hex[:12]}")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceCallOutcomeEvent(BaseModel):
    """Validated webhook/callback event representing call completion or update."""
    external_call_id: str
    appointment_id: str
    clinic_id: Optional[str] = None
    clinic_name: Optional[str] = None
    status: VoiceCallStatus = VoiceCallStatus.COMPLETED
    disposition: VoiceCallDisposition
    available_slots: List[AppointmentSlot] = Field(default_factory=list)
    selected_slot: Optional[AppointmentSlot] = None
    booking_reference: Optional[str] = None
    booking_confirmed: bool = False
    failure_reason: Optional[str] = None
    callback_required: bool = False
    duration_seconds: Optional[int] = None
    idempotency_key: str
    sanitized_notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceCallRecord(BaseModel):
    """Durable database record of a voice call session."""
    call_id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:10]}")
    external_call_id: str
    appointment_id: str
    clinic_id: Optional[str] = None
    clinic_name: Optional[str] = None
    status: VoiceCallStatus = VoiceCallStatus.INITIATED
    disposition: VoiceCallDisposition = VoiceCallDisposition.UNKNOWN
    available_slots: List[AppointmentSlot] = Field(default_factory=list)
    selected_slot: Optional[AppointmentSlot] = None
    booking_outcome: Optional[str] = None
    booking_reference: Optional[str] = None
    failure_reason: Optional[str] = None
    callback_required: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    idempotency_key: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceContextResponse(BaseModel):
    """Non-sensitive, authorized minimal context payload provided to voice coordinator."""
    appointment_id: str
    patient_id: str
    patient_display_name: str
    clinic_id: str
    clinic_name: str
    doctor_name: Optional[str] = None
    preferred_date: str
    preferred_time: Optional[str] = None
    status: str
    requires_approval: bool = False
