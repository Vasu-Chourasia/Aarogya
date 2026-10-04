"""Tests for Module 3: Medicine Availability Workflow."""

from aarogya.workflows.medicine_availability import MedicineAvailabilityWorkflow
from aarogya.connectors.pharmacy_connector import MockDirectPharmacyConnector
from aarogya.models.request import ParsedRequest
from aarogya.models.enums import RequestType, MedicineAvailabilityOutcome, ExecutionStatus


def test_availability_check_available(brain, connector_registry, policy_engine):
    mock_pharmacy = MockDirectPharmacyConnector(simulated_inventory={"medicine x": 50})
    workflow = MedicineAvailabilityWorkflow(
        brain=brain,
        connector_registry=connector_registry,
        policy_engine=policy_engine,
        pharmacy_connector=mock_pharmacy,
    )

    parsed = ParsedRequest(
        request_id="req_test_01",
        requesting_user="usr_amit_01",
        request_type=RequestType.MEDICINE_AVAILABILITY_CHECK,
        patient_id="pat_rajesh_01",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        required_quantity=30,
        execution_status=ExecutionStatus.RECEIVED,
    )

    result = workflow.process_availability_check(parsed)
    assert result.outcome == MedicineAvailabilityOutcome.AVAILABLE
    assert result.available_quantity == 50
    assert result.is_simulated is True
    assert "simulated_direct_pharmacy_api" in result.source


def test_availability_check_out_of_stock(brain, connector_registry, policy_engine):
    mock_pharmacy = MockDirectPharmacyConnector(simulated_inventory={"medicine x": 0})
    workflow = MedicineAvailabilityWorkflow(
        brain=brain,
        connector_registry=connector_registry,
        policy_engine=policy_engine,
        pharmacy_connector=mock_pharmacy,
    )

    parsed = ParsedRequest(
        request_id="req_test_02",
        requesting_user="usr_amit_01",
        request_type=RequestType.MEDICINE_AVAILABILITY_CHECK,
        patient_id="pat_rajesh_01",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine X",
        required_quantity=30,
        execution_status=ExecutionStatus.RECEIVED,
    )

    result = workflow.process_availability_check(parsed)
    assert result.outcome == MedicineAvailabilityOutcome.UNAVAILABLE
    assert result.available_quantity == 0


def test_availability_check_missing_prescription(brain, connector_registry, policy_engine):
    mock_pharmacy = MockDirectPharmacyConnector()
    workflow = MedicineAvailabilityWorkflow(
        brain=brain,
        connector_registry=connector_registry,
        policy_engine=policy_engine,
        pharmacy_connector=mock_pharmacy,
    )

    # Medicine Z is unprescribed
    parsed = ParsedRequest(
        request_id="req_test_03",
        requesting_user="usr_amit_01",
        request_type=RequestType.MEDICINE_AVAILABILITY_CHECK,
        patient_id="pat_rajesh_01",
        patient_name="Rajesh Kumar",
        medicine_name="Medicine Z",
        required_quantity=10,
        execution_status=ExecutionStatus.RECEIVED,
    )

    result = workflow.process_availability_check(parsed)
    assert result.outcome == MedicineAvailabilityOutcome.MISSING_PRESCRIPTION
    assert "No verified prescription found" in result.details
