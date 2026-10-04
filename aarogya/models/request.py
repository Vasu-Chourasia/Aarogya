"""Request data models for Aarogya."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
from .enums import RequestType, ExecutionStatus


class MissingInfoItem(BaseModel):
    """Specification of missing data needed to proceed."""
    field: str
    description: str
    clarification_question: str


class HealthcareRequest(BaseModel):
    """Raw incoming user coordination request."""
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:10]}")
    user_id: str
    raw_text: str
    channel: str = "chat"  # "whatsapp", "voice", "chat", "portal"
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_relationship: Optional[str] = None
    medicine_name: Optional[str] = None
    quantity: Optional[int] = None
    urgency: str = "normal"
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ParsedRequest(BaseModel):
    """Structured request interpretation produced by Module 1."""
    request_id: str
    requesting_user: str
    request_type: RequestType
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_relationship: Optional[str] = None
    medicine_name: Optional[str] = None
    active_ingredient: Optional[str] = None
    strength: Optional[str] = None
    dosage_info: Optional[str] = None
    required_quantity: Optional[int] = None
    prescription_reference: Optional[str] = None
    preferred_pharmacy: Optional[str] = None
    authorization_status: str = "pending_verification"
    urgency: str = "normal"
    required_action: Optional[str] = None
    missing_information: List[MissingInfoItem] = Field(default_factory=list)
    requires_patient_resolution: bool = False
    requires_prescription_verification: bool = False
    requires_pharmacy_connector: bool = False
    execution_status: ExecutionStatus = ExecutionStatus.RECEIVED
    confidence_score: float = 1.0
    idempotency_key: Optional[str] = None
    explanation: Optional[str] = None
