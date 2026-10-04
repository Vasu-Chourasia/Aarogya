"""Module 6: Outcome Verification Service."""

import logging
from typing import Dict, Optional, List, Any
from ..models.execution import ExecutionRecord, OutcomeEvidence
from ..models.enums import ExecutionMode, VerificationStatus

logger = logging.getLogger(__name__)


class OutcomeVerificationService:
    """Manages operational execution records and validates real-world evidence.
    
    Prevents claiming healthcare outcomes without verified external evidence.
    """

    def __init__(self, execution_mode: ExecutionMode = ExecutionMode.SIMULATION):
        self.execution_mode = execution_mode
        self._records: Dict[str, ExecutionRecord] = {}

    def create_execution_record(
        self,
        request_id: str,
        operation_type: str,
        status: str = "planned",
    ) -> ExecutionRecord:
        """Initialize a new execution record."""
        record = ExecutionRecord(
            request_id=request_id,
            operation_type=operation_type,
            execution_mode=self.execution_mode,
            status=status,
            verification_status=VerificationStatus.NOT_APPLICABLE,
        )
        self._records[record.operation_id] = record
        return record

    def record_execution_success(
        self,
        operation_id: str,
        provider_response: Dict[str, Any],
        evidence_description: str,
        evidence_source: str,
        is_delivery_or_clinical: bool = False,
    ) -> Optional[ExecutionRecord]:
        """Record provider response from successful API invocation.
        
        Distinguishes API completion from real-world outcome delivery.
        """
        record = self._records.get(operation_id)
        if not record:
            return None

        record.status = "executed"
        record.provider_response = provider_response

        # Evidence of invocation / creation
        record.add_evidence(
            evidence_type="provider_api_confirmation",
            source=evidence_source,
            description=evidence_description,
            raw_payload=provider_response,
            verified=True,
        )

        # Real-world delivery vs API transaction
        if is_delivery_or_clinical:
            record.verification_status = VerificationStatus.PENDING_VERIFICATION
            record.status = "executed"
        else:
            # Operation was API-bound (e.g., query or task registration)
            record.verification_status = VerificationStatus.VERIFIED
            record.status = "verified"

        return record

    def record_execution_failure(
        self,
        operation_id: str,
        error_message: str,
        provider_response: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExecutionRecord]:
        """Record operational failure."""
        record = self._records.get(operation_id)
        if not record:
            return None

        record.status = "failed"
        record.error_message = error_message
        record.provider_response = provider_response
        record.verification_status = VerificationStatus.VERIFICATION_FAILED
        return record

    def verify_delivery_outcome(
        self,
        operation_id: str,
        evidence_type: str,
        proof_payload: Dict[str, Any],
    ) -> Optional[ExecutionRecord]:
        """Verify real-world delivery using physical/logistical proof (POD, OTP, Caregiver signature)."""
        record = self._records.get(operation_id)
        if not record:
            return None

        # Verify physical delivery proof
        is_valid_proof = bool(proof_payload.get("pod_signature") or proof_payload.get("verified_otp"))
        
        record.add_evidence(
            evidence_type=evidence_type,
            source="logistics_or_caregiver_pod",
            description=f"Delivery verification via {evidence_type}",
            raw_payload=proof_payload,
            verified=is_valid_proof,
        )

        if is_valid_proof:
            record.verification_status = VerificationStatus.VERIFIED
            record.status = "verified"
        else:
            record.verification_status = VerificationStatus.UNVERIFIED
            record.status = "unverified"

        return record

    def get_record(self, operation_id: str) -> Optional[ExecutionRecord]:
        return self._records.get(operation_id)

    def get_records_for_request(self, request_id: str) -> List[ExecutionRecord]:
        return [r for r in self._records.values() if r.request_id == request_id]
