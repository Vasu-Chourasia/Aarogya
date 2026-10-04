"""Domain models for Appointment Coordination."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import uuid
from pydantic import BaseModel, Field

from .enums import AppointmentStatus


class ClinicInfo(BaseModel):
    """Clinic and facility metadata."""
    clinic_id: str
    clinic_name: str
    department: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None


class DoctorInfo(BaseModel):
    """Healthcare provider / physician information."""
    doctor_id: Optional[str] = None
    doctor_name: str
    specialization: Optional[str] = None


class AppointmentSlot(BaseModel):
    """Specific appointment slot offered or approved."""
    slot_id: str = Field(default_factory=lambda: f"slot_{uuid.uuid4().hex[:8]}")
    start_time: str  # ISO-8601 or HH:MM format
    end_time: Optional[str] = None
    date: str  # YYYY-MM-DD
    doctor_name: Optional[str] = None
    clinic_name: Optional[str] = None
    token_number: Optional[str] = None
    notes: Optional[str] = None


class AppointmentRequest(BaseModel):
    """Input payload to initiate appointment coordination."""
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:10]}")
    patient_id: str
    requesting_user_id: str
    clinic: ClinicInfo
    doctor: Optional[DoctorInfo] = None
    preferred_date: str
    preferred_time: Optional[str] = None
    preferred_slot_id: Optional[str] = None
    reason_for_visit: Optional[str] = None  # Non-sensitive high-level category e.g. "routine checkup"
    idempotency_key: Optional[str] = None
    correlation_id: Optional[str] = Field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:12]}")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AppointmentSlotApprovalRequest(BaseModel):
    """Payload when patient/caregiver approves or selects a slot."""
    appointment_id: str
    approving_user_id: str
    slot_id: str
    selected_slot: Optional[AppointmentSlot] = None
    approval_notes: Optional[str] = None
    idempotency_key: Optional[str] = None


class AppointmentRecord(BaseModel):
    """Durable state record for an appointment coordination workflow."""
    appointment_id: str = Field(default_factory=lambda: f"apt_{uuid.uuid4().hex[:10]}")
    request_id: str
    patient_id: str
    requesting_user_id: str
    clinic: ClinicInfo
    doctor: Optional[DoctorInfo] = None
    preferred_date: str
    preferred_time: Optional[str] = None
    status: AppointmentStatus = AppointmentStatus.REQUESTED
    available_slots: List[AppointmentSlot] = Field(default_factory=list)
    approved_slot: Optional[AppointmentSlot] = None
    clinic_booking_reference: Optional[str] = None
    failure_reason: Optional[str] = None
    uncertainty_reason: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    idempotency_key: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
