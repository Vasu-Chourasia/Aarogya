"""Module 9: Execution Gateway Models and Input Validation Contracts.

Enforces strict schemas, extra-field rejection, injection detection,
and structured execution requests and results.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .enums import (
    ExecutionMode,
    GatewayExecutionStatus,
    CapabilityPolicyDecision,
    VerificationStatus,
    TaskPriority,
)

# Common injection pattern guard (SQL, shell, script, template)
INJECTION_PATTERN = re.compile(
    r"(<script|javascript:|;\s*drop\s|;\s*delete\s|;\s*truncate\s|union\s+select|\bexec\s*\(|\beval\s*\(|--|\brm\s+-rf\b|`|\$\()",
    re.IGNORECASE,
)


def validate_safe_string(val: str, field_name: str) -> str:
    """Ensure string inputs do not contain dangerous command or script injection patterns."""
    if not isinstance(val, str):
        return val
    if INJECTION_PATTERN.search(val):
        raise ValueError(f"Field '{field_name}' contains potentially unsafe characters or injection patterns.")
    return val.strip()


# ------------------------------------------------------------------------------
# Input Validation Contracts (extra = "forbid" strictly enforced)
# ------------------------------------------------------------------------------

class CheckInventoryInputContract(BaseModel):
    """Input contract for medicine inventory checking."""
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(..., min_length=1, max_length=150)
    quantity: int = Field(..., gt=0, le=1000)
    pincode: Optional[str] = Field(None, min_length=5, max_length=10)
    dosage: Optional[str] = Field(None, max_length=50)

    @field_validator("medicine_name", "pincode", "dosage")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class GetProductDetailsInputContract(BaseModel):
    """Input contract for querying product details from pharmacy catalog."""
    model_config = ConfigDict(extra="forbid")

    medicine_name: Optional[str] = Field(None, min_length=1, max_length=150)
    product_id: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("medicine_name", "product_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v

    def model_post_init(self, __context: Any) -> None:
        if not self.medicine_name and not self.product_id:
            raise ValueError("Either 'medicine_name' or 'product_id' must be provided.")


class GetPriceInputContract(BaseModel):
    """Input contract for querying medicine price."""
    model_config = ConfigDict(extra="forbid")

    medicine_name: Optional[str] = Field(None, min_length=1, max_length=150)
    product_id: Optional[str] = Field(None, min_length=1, max_length=100)
    quantity: int = Field(1, gt=0, le=1000)

    @field_validator("medicine_name", "product_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v

    def model_post_init(self, __context: Any) -> None:
        if not self.medicine_name and not self.product_id:
            raise ValueError("Either 'medicine_name' or 'product_id' must be provided.")


class CheckDeliveryCoverageInputContract(BaseModel):
    """Input contract for checking delivery serviceability for a pincode."""
    model_config = ConfigDict(extra="forbid")

    pincode: str = Field(..., min_length=5, max_length=10)
    medicine_name: Optional[str] = Field(None, min_length=1, max_length=150)

    @field_validator("pincode", "medicine_name")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class GetOrderStatusInputContract(BaseModel):
    """Input contract for checking order status with existing sandbox/synthetic order ID."""
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(..., min_length=1, max_length=100)
    patient_id: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("order_id", "patient_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class ReserveStockInputContract(BaseModel):
    """Input contract for reserving medicine stock."""
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(..., min_length=1, max_length=150)
    quantity: int = Field(..., gt=0, le=500)
    patient_id: str = Field(..., min_length=1, max_length=100)
    prescription_id: Optional[str] = Field(None, max_length=100)
    reservation_hours: int = Field(24, gt=0, le=72)

    @field_validator("medicine_name", "patient_id", "prescription_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class CreateOrderInputContract(BaseModel):
    """Input contract for placing medicine orders."""
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(..., min_length=1, max_length=150)
    quantity: int = Field(..., gt=0, le=500)
    patient_id: str = Field(..., min_length=1, max_length=100)
    delivery_address: str = Field(..., min_length=5, max_length=300)
    prescription_id: str = Field(..., min_length=1, max_length=100)
    price: Optional[float] = Field(None, gt=0)

    @field_validator("medicine_name", "patient_id", "delivery_address", "prescription_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class CreateCaregiverTaskInputContract(BaseModel):
    """Input contract for creating caregiver tasks."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    patient_id: str = Field(..., min_length=1, max_length=100)
    assigned_to: str = Field(..., min_length=1, max_length=100)
    priority: TaskPriority = TaskPriority.NORMAL
    due_date: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=1000)

    @field_validator("title", "patient_id", "assigned_to", "due_date", "description")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class QueryCaregiverTaskInputContract(BaseModel):
    """Input contract for querying caregiver tasks."""
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., min_length=1, max_length=100)
    task_id: Optional[str] = Field(None, max_length=100)

    @field_validator("patient_id", "task_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class InitiatePaymentInputContract(BaseModel):
    """Input contract for initiating co-pay / medicine payment."""
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(..., min_length=1, max_length=100)
    patient_id: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0)
    currency: str = Field("INR", max_length=10)

    @field_validator("order_id", "patient_id", "currency")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class TrackDeliveryInputContract(BaseModel):
    """Input contract for tracking medicine delivery."""
    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(..., min_length=1, max_length=100)
    patient_id: Optional[str] = Field(None, max_length=100)

    @field_validator("tracking_number", "patient_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class DiscoverSlotsInputContract(BaseModel):
    """Input contract for discovering appointment slots at a clinic."""
    model_config = ConfigDict(extra="forbid")

    clinic_id: str = Field(..., min_length=1, max_length=100)
    preferred_date: str = Field(..., min_length=8, max_length=20)
    doctor_name: Optional[str] = Field(None, max_length=150)
    patient_id: Optional[str] = Field(None, max_length=100)

    @field_validator("clinic_id", "preferred_date", "doctor_name", "patient_id")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class BookAppointmentInputContract(BaseModel):
    """Input contract for booking an approved appointment slot."""
    model_config = ConfigDict(extra="forbid")

    appointment_id: str = Field(..., min_length=1, max_length=100)
    clinic_id: str = Field(..., min_length=1, max_length=100)
    slot_id: str = Field(..., min_length=1, max_length=100)
    patient_id: str = Field(..., min_length=1, max_length=100)
    doctor_name: Optional[str] = Field(None, max_length=150)

    @field_validator("appointment_id", "clinic_id", "slot_id", "patient_id", "doctor_name")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


class InitiateVoiceCallInputContract(BaseModel):
    """Input contract for initiating an outbound clinic voice call."""
    model_config = ConfigDict(extra="forbid")

    appointment_id: str = Field(..., min_length=1, max_length=100)
    clinic_id: str = Field(..., min_length=1, max_length=100)
    clinic_phone: str = Field(..., min_length=5, max_length=30)
    patient_id: str = Field(..., min_length=1, max_length=100)
    preferred_date: str = Field(..., min_length=8, max_length=20)
    preferred_time: Optional[str] = Field(None, max_length=20)
    doctor_name: Optional[str] = Field(None, max_length=150)

    @field_validator("appointment_id", "clinic_id", "clinic_phone", "patient_id", "preferred_date", "preferred_time", "doctor_name")
    @classmethod
    def sanitize_strings(cls, v: Optional[str], info):
        if v is not None:
            return validate_safe_string(v, info.field_name)
        return v


# ------------------------------------------------------------------------------
# Execution Request & Result Models
# ------------------------------------------------------------------------------

class ExecutionRequest(BaseModel):
    """Structured request submitted to the Aarogya Execution Gateway."""
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:10]}")
    capability_id: str
    requested_operation: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    workflow_id: str = "healthcare_coordination"
    requesting_user_id: str
    patient_id: Optional[str] = None
    authorization_context: Optional[Dict[str, Any]] = None
    approval_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    execution_mode: ExecutionMode = ExecutionMode.SIMULATION
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionResult(BaseModel):
    """Structured, policy-verified result returned by the Execution Gateway."""
    execution_id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:10]}")
    request_id: str
    capability_id: str
    operation: str
    status: GatewayExecutionStatus
    policy_decision: CapabilityPolicyDecision
    handler_invoked: bool = False
    is_simulated: bool = False
    output: Optional[Dict[str, Any]] = None
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    verification_status: VerificationStatus = VerificationStatus.NOT_APPLICABLE
    idempotency_matched: bool = False
