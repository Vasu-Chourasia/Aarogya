"""Tests for Module 1: Request Understanding."""

from aarogya.models.request import HealthcareRequest
from aarogya.models.enums import RequestType, ExecutionStatus
from aarogya.understanding.request_parser import RequestUnderstandingService


def test_missing_medicine_and_quantity_returns_blocked(brain):
    parser = RequestUnderstandingService(brain)
    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check whether my father's prescribed medicine is available.",
    )
    parsed = parser.parse(req)

    assert parsed.request_type == RequestType.MEDICINE_AVAILABILITY_CHECK
    assert parsed.patient_relationship == "father"
    assert parsed.medicine_name is None
    assert parsed.required_quantity is None
    assert parsed.execution_status == ExecutionStatus.BLOCKED_MISSING_INFORMATION
    
    missing_fields = [m.field for m in parsed.missing_information]
    assert "medicine_name" in missing_fields
    assert "quantity" in missing_fields


def test_complete_request_parsing(brain):
    parser = RequestUnderstandingService(brain)
    req = HealthcareRequest(
        user_id="usr_amit_01",
        raw_text="Check if Medicine X 30 tablets is available for Rajesh Kumar.",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        quantity=30,
    )
    parsed = parser.parse(req)

    assert parsed.request_type == RequestType.MEDICINE_AVAILABILITY_CHECK
    assert parsed.patient_id == "pat_rajesh_01"
    assert parsed.patient_name == "Rajesh Kumar"
    assert parsed.medicine_name == "Medicine X"
    assert parsed.required_quantity == 30
    assert parsed.active_ingredient == "Metformin Hydrochloride"
    assert parsed.strength == "500mg"
    assert parsed.prescription_reference == "rx_rajesh_2026_01"
    assert parsed.execution_status == ExecutionStatus.RECEIVED
    assert len(parsed.missing_information) == 0
