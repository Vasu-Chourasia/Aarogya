"""Patient, Prescription, and Family Health Brain models."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import date, datetime


class MedicineItem(BaseModel):
    """Verified prescribed medicine."""
    medicine_name: str
    active_ingredient: Optional[str] = None
    strength: Optional[str] = None  # e.g., "500mg"
    form: str = "tablet"            # "tablet", "syrup", "capsule", "injection"
    dosage_instruction: str         # e.g., "1 tablet twice daily after meals"
    quantity_prescribed: int
    duration_days: int
    refills_allowed: int = 0
    refills_remaining: int = 0


class PrescriptionRecord(BaseModel):
    """Verified prescription record in Family Health Brain."""
    prescription_id: str
    patient_id: str
    doctor_name: str
    doctor_registration_number: Optional[str] = None
    clinic_or_hospital: str
    issue_date: date
    valid_until: date
    medicines: List[MedicineItem] = Field(default_factory=list)
    is_verified: bool = True
    verification_source: str = "doctor_upload"  # "whatsapp_ocr_verified", "doctor_portal", "hospital_ehr"
    verified_at: Optional[datetime] = None
    verification_notes: Optional[str] = None


class MedicinePlan(BaseModel):
    """Active daily medicine schedule for a patient."""
    plan_id: str
    patient_id: str
    prescription_id: str
    medicine_name: str
    strength: str
    dosage: str
    frequency: str
    current_inventory_count: int = 0
    reorder_threshold: int = 5
    last_refill_date: Optional[date] = None


class FamilyMember(BaseModel):
    """Family circle member associated with patient care."""
    member_id: str
    full_name: str
    relationship_to_patient: str  # "father", "mother", "son", "daughter", "spouse", "self"
    contact_number: Optional[str] = None
    is_primary_caregiver: bool = False
    is_authorized_payer: bool = False
    permissions: List[str] = Field(default_factory=lambda: ["view_records"])


class PatientRecord(BaseModel):
    """Verified Patient Record in Family Health Brain."""
    patient_id: str
    full_name: str
    date_of_birth: Optional[date] = None
    gender: str = "Unknown"
    chronic_conditions: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    family_members: List[FamilyMember] = Field(default_factory=list)
    prescriptions: List[PrescriptionRecord] = Field(default_factory=list)
    medicine_plans: List[MedicinePlan] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
