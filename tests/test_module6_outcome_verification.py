"""Tests for Module 6: Outcome Verification Service."""

from aarogya.workflows.verification import OutcomeVerificationService
from aarogya.models.enums import VerificationStatus, ExecutionMode


def test_api_success_differentiated_from_real_world_delivery():
    verifier = OutcomeVerificationService(ExecutionMode.SIMULATION)
    rec = verifier.create_execution_record("req_order_01", "medicine_order")
    
    # 1. API success is recorded, but for clinical/delivery it marks PENDING_VERIFICATION
    verifier.record_execution_success(
        operation_id=rec.operation_id,
        provider_response={"order_id": "ord_123", "status": "accepted"},
        evidence_description="Order placed with pharmacy",
        evidence_source="pharmacy_api",
        is_delivery_or_clinical=True,
    )
    
    updated = verifier.get_record(rec.operation_id)
    assert updated.status == "executed"
    assert updated.verification_status == VerificationStatus.PENDING_VERIFICATION

    # 2. Complete delivery only after real-world proof (POD / OTP)
    verifier.verify_delivery_outcome(
        operation_id=rec.operation_id,
        evidence_type="proof_of_delivery",
        proof_payload={"pod_signature": "sig_caregiver_received", "otp_verified": True},
    )

    final = verifier.get_record(rec.operation_id)
    assert final.status == "verified"
    assert final.verification_status == VerificationStatus.VERIFIED
