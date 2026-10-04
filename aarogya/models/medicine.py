"""Medicine Availability models for Aarogya."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from .enums import MedicineAvailabilityOutcome


class MedicineAvailabilityRequest(BaseModel):
    """Input payload to check medicine availability."""
    patient_id: str
    medicine_name: str
    required_quantity: int
    strength: Optional[str] = None
    prescription_id: Optional[str] = None
    preferred_pharmacy: Optional[str] = None


class PharmacyInventoryItem(BaseModel):
    """Stock item returned by a pharmacy connector."""
    pharmacy_id: str
    pharmacy_name: str
    medicine_name: str
    strength: Optional[str] = None
    available_stock: int
    unit_price: Optional[float] = None
    currency: str = "INR"
    batch_expiry: Optional[str] = None
    verified_at: datetime = Field(default_factory=datetime.utcnow)


class MedicineAvailabilityResult(BaseModel):
    """Structured result of a medicine availability check."""
    outcome: MedicineAvailabilityOutcome
    patient_id: str
    medicine_name: str
    required_quantity: int
    available_quantity: int = 0
    pharmacy_name: Optional[str] = None
    pharmacy_id: Optional[str] = None
    unit_price: Optional[float] = None
    total_estimated_price: Optional[float] = None
    source: str
    is_simulated: bool = False
    details: str
    raw_provider_response: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
