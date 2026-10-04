"""Audit Logging Models."""

from typing import Optional, Dict, Any
from datetime import datetime
import uuid
from pydantic import BaseModel, Field
from .enums import AuditEventType, ExecutionMode


class AuditLogEntry(BaseModel):
    """Structured, tamper-evident audit log event."""
    audit_id: str = Field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:12]}")
    event_type: AuditEventType
    request_id: Optional[str] = None
    patient_id: Optional[str] = None
    user_id: Optional[str] = None
    operation_type: Optional[str] = None
    status: str
    details: str
    execution_mode: ExecutionMode = ExecutionMode.SIMULATION
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
