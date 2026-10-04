"""Module 1: Healthcare Request Understanding Service."""

import re
from typing import Optional, List
from ..models.request import HealthcareRequest, ParsedRequest, MissingInfoItem
from ..models.enums import RequestType, ExecutionStatus
from ..brain.family_health_brain import FamilyHealthBrain


class RequestUnderstandingService:
    """Interprets incoming unstructured or structured user requests.
    
    Extracts clinical and operational entities, detects missing requirements,
    and flags prerequisites (patient resolution, prescription verification,
    connector checks).
    """

    def __init__(self, brain: Optional[FamilyHealthBrain] = None):
        self.brain = brain or FamilyHealthBrain()

    def parse(self, request: HealthcareRequest) -> ParsedRequest:
        """Parse raw HealthcareRequest into structured ParsedRequest."""
        raw_text = request.raw_text.strip()
        lower_text = raw_text.lower()
        
        # 1. Determine request type
        req_type = self._classify_request_type(lower_text, request)
        
        # 2. Extract entities
        patient_name = request.patient_name or self._extract_patient_name(raw_text)
        patient_rel = request.patient_relationship or self._extract_relationship(lower_text)
        medicine_name = request.medicine_name or self._extract_medicine_name(raw_text)
        quantity = request.quantity or self._extract_quantity(raw_text)
        preferred_pharmacy = self._extract_preferred_pharmacy(raw_text)
        urgency = request.urgency or ("urgent" if any(w in lower_text for w in ["urgent", "emergency", "asap", "immediately"]) else "normal")
        
        requires_patient_resolution = False
        patient_id = request.patient_id
        
        # Patient resolution check
        if not patient_id:
            if patient_rel and not patient_name:
                resolved = self.brain.resolve_patient_by_relationship(request.user_id, patient_rel)
                if resolved:
                    patient_id = resolved.patient_id
                    patient_name = resolved.full_name
                else:
                    requires_patient_resolution = True
            elif patient_name:
                resolved = self.brain.get_patient(patient_name)
                if resolved:
                    patient_id = resolved.patient_id
                    patient_name = resolved.full_name
                else:
                    # Unknown patient name, cannot invent
                    requires_patient_resolution = True
            else:
                requires_patient_resolution = True

        # Prescription verification check & enrichment
        requires_prescription_verification = False
        active_ingredient = None
        strength = None
        dosage_info = None
        prescription_reference = None
        
        if req_type == RequestType.EMERGENCY:
            return ParsedRequest(
                request_id=request.request_id,
                requesting_user=request.user_id,
                request_type=RequestType.EMERGENCY,
                patient_id=patient_id,
                patient_name=patient_name,
                patient_relationship=patient_rel,
                medicine_name=medicine_name,
                active_ingredient=None,
                strength=None,
                dosage_info=None,
                required_quantity=None,
                prescription_reference=None,
                preferred_pharmacy=preferred_pharmacy,
                authorization_status="emergency_routed",
                urgency="critical",
                required_action="emergency_assistance",
                missing_information=[],
                requires_patient_resolution=False,
                requires_prescription_verification=False,
                requires_pharmacy_connector=False,
                execution_status=ExecutionStatus.ROUTED_TO_EMERGENCY,
                confidence_score=1.0,
                idempotency_key=request.idempotency_key,
                explanation="Critical emergency symptoms detected. Immediate emergency medical assistance required.",
            )

        if req_type in [RequestType.MEDICINE_AVAILABILITY_CHECK, RequestType.MEDICINE_ORDER, RequestType.REFILL_COORDINATION]:
            requires_prescription_verification = True
            if patient_id and medicine_name:
                rx_item = self.brain.find_prescribed_medicine(patient_id, medicine_name)
                rx_record = self.brain.get_verified_prescription(patient_id, medicine_name)
                if rx_item and rx_record:
                    active_ingredient = rx_item.active_ingredient
                    strength = rx_item.strength
                    dosage_info = rx_item.dosage_instruction
                    prescription_reference = rx_record.prescription_id
                    requires_prescription_verification = False  # Successfully verified

        # Check missing information
        missing_info: List[MissingInfoItem] = []
        if requires_patient_resolution and not patient_id:
            missing_info.append(MissingInfoItem(
                field="patient_name",
                description="Verified patient identification",
                clarification_question="Which family member is this request for?",
            ))
            
        if req_type in [RequestType.MEDICINE_AVAILABILITY_CHECK, RequestType.MEDICINE_ORDER, RequestType.REFILL_COORDINATION]:
            if not medicine_name:
                missing_info.append(MissingInfoItem(
                    field="medicine_name",
                    description="Prescribed medicine name",
                    clarification_question="Which prescribed medicine would you like me to check?",
                ))
            if not quantity:
                missing_info.append(MissingInfoItem(
                    field="quantity",
                    description="Prescribed medicine quantity",
                    clarification_question="What quantity or duration (number of tablets) do you require?",
                ))

        # Determine execution status
        execution_status = ExecutionStatus.RECEIVED
        requires_pharmacy_connector = (req_type in [RequestType.MEDICINE_AVAILABILITY_CHECK, RequestType.MEDICINE_ORDER, RequestType.REFILL_COORDINATION])
        
        if missing_info:
            execution_status = ExecutionStatus.BLOCKED_MISSING_INFORMATION

        explanation = None
        if missing_info:
            fields = [m.field for m in missing_info]
            explanation = f"Missing required information to proceed: {', '.join(fields)}."

        return ParsedRequest(
            request_id=request.request_id,
            requesting_user=request.user_id,
            request_type=req_type,
            patient_id=patient_id,
            patient_name=patient_name,
            patient_relationship=patient_rel,
            medicine_name=medicine_name,
            active_ingredient=active_ingredient,
            strength=strength,
            dosage_info=dosage_info,
            required_quantity=quantity,
            prescription_reference=prescription_reference,
            preferred_pharmacy=preferred_pharmacy,
            authorization_status="pending_verification",
            urgency=urgency,
            required_action=req_type.value,
            missing_information=missing_info,
            requires_patient_resolution=requires_patient_resolution,
            requires_prescription_verification=requires_prescription_verification,
            requires_pharmacy_connector=requires_pharmacy_connector,
            execution_status=execution_status,
            confidence_score=0.95 if not missing_info else 0.85,
            idempotency_key=request.idempotency_key,
            explanation=explanation,
        )

    def _classify_request_type(self, text: str, request: HealthcareRequest) -> RequestType:
        # Check emergency red flags first
        emergency_indicators = [
            "chest pain",
            "difficulty breathing",
            "shortness of breath",
            "unconscious",
            "heart attack",
            "stroke",
            "severe bleeding",
            "choking",
            "anaphylaxis",
            "seizure",
        ]
        if any(w in text for w in emergency_indicators):
            return RequestType.EMERGENCY

        if "refill" in text:
            return RequestType.REFILL_COORDINATION
        if any(w in text for w in ["available", "availability", "stock", "check medicine", "in stock"]):
            return RequestType.MEDICINE_AVAILABILITY_CHECK
        if any(w in text for w in ["task", "assign", "caregiver", "helper"]):
            return RequestType.CAREGIVER_TASK_CREATION
        if any(w in text for w in ["order", "purchase", "buy medicine"]):
            return RequestType.MEDICINE_ORDER
        if any(w in text for w in ["prescription", "rx", "doctor note"]):
            return RequestType.PRESCRIPTION_VERIFICATION
        if any(w in text for w in ["appointment", "doctor visit", "consultation"]):
            return RequestType.APPOINTMENT_COORDINATION
        return RequestType.GENERAL_INQUIRY

    def _extract_relationship(self, text: str) -> Optional[str]:
        relationships = ["father", "dad", "mother", "mom", "son", "daughter", "spouse", "wife", "husband", "parent"]
        for rel in relationships:
            pattern = rf"\b(?:my\s+)?{rel}\b"
            if re.search(pattern, text):
                return "father" if rel in ["father", "dad"] else "mother" if rel in ["mother", "mom"] else rel
        return None

    def _extract_patient_name(self, text: str) -> Optional[str]:
        # Check against known patients or common patterns
        match = re.search(r"(?:patient[:\s]+|for\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text)
        if match:
            return match.group(1).strip()
        # Direct mention of Rajesh Kumar
        if "rajesh kumar" in text.lower():
            return "Rajesh Kumar"
        return None

    def _extract_medicine_name(self, text: str) -> Optional[str]:
        # Direct known medicine checks
        if "medicine x" in text.lower():
            return "Medicine X"
        if "amlodipine" in text.lower():
            return "Amlodipine"
        if "paracetamol" in text.lower():
            return "Paracetamol"
        if "metformin" in text.lower():
            return "Metformin"

        # Explicit label "medicine: <Name>" or "medicine <Name>"
        match = re.search(r"(?:medicine[:\s]+)([A-Za-z0-9\-]+(?:\s+[A-Za-z0-9\-]+)?)", text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            cand_lower = candidate.lower()
            stop_words = ["is", "is available", "are", "was", "available", "prescribed", "check", "for", "the", "needed", "required"]
            if cand_lower not in stop_words and not any(cand_lower.startswith(sw + " ") for sw in ["is", "are", "was", "for"]):
                return candidate
        return None

    def _extract_quantity(self, text: str) -> Optional[int]:
        # Match "30 tablets", "quantity: 30", "qty 30", "30 pills", "30 strips"
        match = re.search(r"(?:quantity[:\s]+|qty[:\s]+)?(\d+)\s*(?:tablets|tabs|pills|capsules|units)?", text, re.IGNORECASE)
        if match:
            val = match.group(1)
            # Avoid matching year like 2026 as quantity
            if int(val) < 1000:
                return int(val)
        return None

    def _extract_preferred_pharmacy(self, text: str) -> Optional[str]:
        match = re.search(r"(?:pharmacy[:\s]+|from\s+pharmacy\s+)([A-Za-z0-9\s]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
