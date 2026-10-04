"""Execution Record and Outcome Verification models."""

from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
from pydantic import BaseModel, Field
from .enums import ExecutionMode, VerificationStatus


class OutcomeEvidence(BaseModel):
    """Verifiable proof of an operational or real-world healthcare outcome."""
    evidence_id: str = Field(default_factory=lambda: f"evd_{uuid.uuid4().hex[:10]}")
    evidence_type: str  # e.g., "pharmacy_api_response", "task_backend_confirmation", "caregiver_acknowledgment", "delivery_pod"
    source: str
    description: str
    verified: bool = False
    raw_payload: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionRecord(BaseModel):
    """Traceable execution record for every attempted operation."""
    operation_id: str = Field(default_factory=lambda: f"op_{uuid.uuid4().hex[:10]}")
    request_id: str
    operation_type: str  # e.g., "medicine_availability_check", "caregiver_task_creation", "medicine_order"
    execution_mode: ExecutionMode = ExecutionMode.SIMULATION
    status: str = "planned"  # "planned", "awaiting_approval", "executed", "failed", "verified", "unverified"
    provider_response: Optional[Dict[str, Any]] = None
    verification_status: VerificationStatus = VerificationStatus.NOT_APPLICABLE
    evidence: List[OutcomeEvidence] = Field(default_factory=list)
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def add_evidence(self, evidence_type: str, source: str, description: str, raw_payload: Optional[Dict[str, Any]] = None, verified: bool = True):
        self.evidence.append(OutcomeEvidence(
            evidence_type=evidence_type,
            source=source,
            description=description,
            verified=verified,
            raw_payload=raw_payload,
        ))
