"""Family Health Brain — Central repository of verified family healthcare records."""

from typing import Dict, Optional, List
from datetime import date, datetime
from ..models.patient import (
    PatientRecord,
    PrescriptionRecord,
    MedicinePlan,
    FamilyMember,
    MedicineItem,
)


class FamilyHealthBrain:
    """In-memory verified health brain for Aarogya operations.
    
    Ensures that all operations use verified healthcare records rather
    than assumptions or hallucinated data.
    """

    def __init__(self, seed_fictional_data: bool = True):
        self._patients: Dict[str, PatientRecord] = {}
        self._timeline_events: List[Dict] = []
        if seed_fictional_data:
            self._seed_default_fictional_data()

    def _seed_default_fictional_data(self):
        """Seed established fictional records (e.g., Rajesh Kumar from Phase 1)."""
        rajesh = PatientRecord(
            patient_id="pat_rajesh_01",
            full_name="Rajesh Kumar",
            date_of_birth=date(1956, 4, 12),
            gender="Male",
            chronic_conditions=["Hypertension", "Type 2 Diabetes"],
            allergies=["Penicillin"],
            family_members=[
                FamilyMember(
                    member_id="usr_amit_01",
                    full_name="Amit Kumar",
                    relationship_to_patient="father",  # Amit is Rajesh's son, relation from Amit's perspective is father
                    contact_number="+91-9876543210",
                    is_primary_caregiver=True,
                    is_authorized_payer=True,
                    permissions=[
                        "view_records",
                        "check_medicine",
                        "create_tasks",
                        "approve_orders",
                    ],
                ),
                FamilyMember(
                    member_id="usr_priya_02",
                    full_name="Priya Kumar",
                    relationship_to_patient="father",  # Priya is Rajesh's daughter
                    contact_number="+91-9876543211",
                    is_primary_caregiver=False,
                    is_authorized_payer=False,
                    permissions=["view_records", "check_medicine"],
                ),
            ],
            prescriptions=[
                PrescriptionRecord(
                    prescription_id="rx_rajesh_2026_01",
                    patient_id="pat_rajesh_01",
                    doctor_name="Dr. Ananya Sharma",
                    doctor_registration_number="MCI-2012-44589",
                    clinic_or_hospital="Apollo Clinic, Bangalore",
                    issue_date=date(2026, 1, 15),
                    valid_until=date(2026, 12, 31),
                    medicines=[
                        MedicineItem(
                            medicine_name="Medicine X",
                            active_ingredient="Metformin Hydrochloride",
                            strength="500mg",
                            form="tablet",
                            dosage_instruction="1 tablet twice daily after meals",
                            quantity_prescribed=60,
                            duration_days=30,
                            refills_allowed=3,
                            refills_remaining=2,
                        ),
                        MedicineItem(
                            medicine_name="Amlodipine",
                            active_ingredient="Amlodipine Besylate",
                            strength="5mg",
                            form="tablet",
                            dosage_instruction="1 tablet once daily in the morning",
                            quantity_prescribed=30,
                            duration_days=30,
                            refills_allowed=2,
                            refills_remaining=1,
                        ),
                    ],
                    is_verified=True,
                    verification_source="doctor_portal",
                    verified_at=datetime(2026, 1, 15, 10, 30),
                    verification_notes="Verified via hospital EHR link",
                )
            ],
            medicine_plans=[
                MedicinePlan(
                    plan_id="plan_rx_01",
                    patient_id="pat_rajesh_01",
                    prescription_id="rx_rajesh_2026_01",
                    medicine_name="Medicine X",
                    strength="500mg",
                    dosage="1 tablet twice daily",
                    frequency="BID",
                    current_inventory_count=4,
                    reorder_threshold=10,
                    last_refill_date=date(2026, 1, 15),
                )
            ],
        )
        self._patients[rajesh.patient_id] = rajesh

        # Demonstration Patient 2: Sunita Kumar (Mother of Amit Kumar)
        sunita = PatientRecord(
            patient_id="pat_sunita_02",
            full_name="Sunita Kumar",
            date_of_birth=date(1962, 5, 20),
            gender="Female",
            chronic_conditions=["Hypothyroidism"],
            allergies=[],
            family_members=[
                FamilyMember(
                    member_id="usr_amit_01",
                    full_name="Amit Kumar",
                    relationship_to_patient="mother",  # Relation from Amit's perspective is mother
                    contact_number="+91-9876543210",
                    is_primary_caregiver=True,
                    is_authorized_payer=True,
                    permissions=[
                        "view_records",
                        "check_medicine",
                        "create_tasks",
                        "approve_orders",
                    ],
                ),
                FamilyMember(
                    member_id="usr_priya_02",
                    full_name="Priya Kumar",
                    relationship_to_patient="mother",
                    contact_number="+91-9876543211",
                    is_primary_caregiver=False,
                    is_authorized_payer=False,
                    permissions=["view_records", "check_medicine"],
                ),
            ],
            prescriptions=[
                PrescriptionRecord(
                    prescription_id="rx_sunita_2026_01",
                    patient_id="pat_sunita_02",
                    doctor_name="Dr. Ananya Sharma",
                    doctor_registration_number="MCI-2012-44589",
                    clinic_or_hospital="Apollo Clinic, Bangalore",
                    issue_date=date(2026, 1, 15),
                    valid_until=date(2026, 12, 31),
                    medicines=[
                        MedicineItem(
                            medicine_name="Thyronorm",
                            active_ingredient="Levothyroxine Sodium",
                            strength="50mcg",
                            form="tablet",
                            dosage_instruction="1 tablet once daily in the morning on an empty stomach",
                            quantity_prescribed=30,
                            duration_days=30,
                            refills_allowed=3,
                            refills_remaining=2,
                        ),
                    ],
                    is_verified=True,
                    verification_source="doctor_portal",
                    verified_at=datetime(2026, 1, 15, 10, 30),
                    verification_notes="Verified via hospital EHR link",
                )
            ],
            medicine_plans=[
                MedicinePlan(
                    plan_id="plan_rx_sunita_01",
                    patient_id="pat_sunita_02",
                    prescription_id="rx_sunita_2026_01",
                    medicine_name="Thyronorm",
                    strength="50mcg",
                    dosage="1 tablet once daily",
                    frequency="OD",
                    current_inventory_count=25,
                    reorder_threshold=10,
                    last_refill_date=date(2026, 1, 15),
                )
            ],
        )
        self._patients[sunita.patient_id] = sunita

    def get_patient(self, patient_id_or_name: str) -> Optional[PatientRecord]:
        """Lookup patient by exact ID or case-insensitive full or first name."""
        if patient_id_or_name in self._patients:
            return self._patients[patient_id_or_name]
        
        normalized = patient_id_or_name.strip().lower()
        for patient in self._patients.values():
            if patient.full_name.strip().lower() == normalized:
                return patient
            # Also allow matching by single name (e.g. 'Rajesh' or 'Sunita')
            if patient.full_name.strip().lower().split()[0] == normalized:
                return patient
        return None

    def resolve_patient_by_relationship(self, user_id: str, relationship: str) -> Optional[PatientRecord]:
        """Resolve patient when user refers to relationship (e.g. 'my father', 'my mother')."""
        norm_rel = relationship.strip().lower()
        for prefix in ["my ", "the ", "our "]:
            if norm_rel.startswith(prefix):
                norm_rel = norm_rel[len(prefix):].strip()

        for patient in self._patients.values():
            for member in patient.family_members:
                if member.member_id == user_id and member.relationship_to_patient.lower() == norm_rel:
                    return patient
                # Also check relationship symmetry if relationship entered inversely
                if member.member_id == user_id:
                    if norm_rel in ["father", "dad", "papa"] and patient.gender == "Male":
                        return patient
                    if norm_rel in ["mother", "mom", "maa", "mummy"] and patient.gender == "Female":
                        return patient
        return None

    def get_verified_prescription(
        self, patient_id: str, medicine_name: Optional[str] = None
    ) -> Optional[PrescriptionRecord]:
        """Retrieve verified active prescription for patient and optional medicine."""
        patient = self.get_patient(patient_id)
        if not patient:
            return None

        today = date.today()
        for rx in patient.prescriptions:
            if not rx.is_verified:
                continue
            if rx.valid_until < today:
                continue
            if medicine_name:
                norm_med = medicine_name.strip().lower()
                matches = any(m.medicine_name.strip().lower() == norm_med for m in rx.medicines)
                if matches:
                    return rx
            else:
                return rx
        return None

    def find_prescribed_medicine(
        self, patient_id: str, medicine_name: str
    ) -> Optional[MedicineItem]:
        """Retrieve specific verified medicine item from patient prescription."""
        rx = self.get_verified_prescription(patient_id, medicine_name)
        if not rx:
            return None
        norm_med = medicine_name.strip().lower()
        for item in rx.medicines:
            if item.medicine_name.strip().lower() == norm_med:
                return item
        return None

    def record_timeline_event(self, event: Dict):
        """Append an event to the Family Health Brain healthcare history."""
        event["recorded_at"] = datetime.utcnow().isoformat()
        self._timeline_events.append(event)

    def get_timeline(self, patient_id: str) -> List[Dict]:
        """Retrieve chronological healthcare events for a patient."""
        return [e for e in self._timeline_events if e.get("patient_id") == patient_id]
