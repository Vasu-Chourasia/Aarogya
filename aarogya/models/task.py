"""Caregiver Task models for Aarogya."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, date
import uuid
from .enums import TaskStatus, TaskPriority


class CaregiverTaskCreateRequest(BaseModel):
    """Specification to create a caregiver task."""
    patient_id: str
    medicine_reference: Optional[str] = None
    required_quantity: Optional[int] = None
    task_description: str
    assigned_caregiver: str
    priority: TaskPriority = TaskPriority.NORMAL
    due_date: Optional[date] = None
    approval_reference: str  # Mandatory link to HITL approval
    idempotency_key: Optional[str] = None


class CaregiverTask(BaseModel):
    """Controlled caregiver task with strict status lifecycle."""
    task_id: str = Field(default_factory=lambda: f"tsk_{uuid.uuid4().hex[:10]}")
    patient_id: str
    medicine_reference: Optional[str] = None
    required_quantity: Optional[int] = None
    task_description: str
    assigned_caregiver: str
    priority: TaskPriority = TaskPriority.NORMAL
    due_date: Optional[date] = None
    approval_reference: str
    creation_timestamp: datetime = Field(default_factory=datetime.utcnow)
    current_status: TaskStatus = TaskStatus.DRAFT
    outcome_evidence: List[str] = Field(default_factory=list)
    is_simulation: bool = False
    backend_type: str = "local_development_task_backend"
    idempotency_key: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)
