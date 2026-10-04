"""Phase 14 Tests: Appointment Coordination, Voice Integration, SQLite Persistence & FastAPI."""

from __future__ import annotations

import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

from aarogya.config import Settings, ExecutionMode
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.policy.authorization_engine import PolicyAuthorizationEngine
from aarogya.workflows.approval_manager import ApprovalManager
from aarogya.workflows.appointment_coordination import AppointmentCoordinationWorkflow
from aarogya.connectors.gnani_adapter import MockGnaniVoiceProvider, VoiceCallResult
from aarogya.persistence import get_persistence_bundle, SQLiteStore, CURRENT_SCHEMA_VERSION
from aarogya.persistence.migrations import SchemaMigrator
from aarogya.models.appointment import (
    AppointmentRequest,
    AppointmentRecord,
    AppointmentSlot,
    AppointmentSlotApprovalRequest,
    ClinicInfo,
    DoctorInfo,
)
from aarogya.models.voice import (
    VoiceCallRequest,
    VoiceCallOutcomeEvent,
    VoiceCallRecord,
    VoiceContextResponse,
)
from aarogya.models.enums import (
    AppointmentStatus,
    VoiceCallStatus,
    VoiceCallDisposition,
    ActionType,
    AuditEventType,
)
from aarogya.api.app import create_app


# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------
@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def persistence_bundle(temp_db):
    bundle = get_persistence_bundle(temp_db)
    yield bundle
    bundle.store.close()


@pytest.fixture
def brain():
    return FamilyHealthBrain(seed_fictional_data=True)


@pytest.fixture
def policy_engine(brain):
    return PolicyAuthorizationEngine(brain)


@pytest.fixture
def workflow(brain, policy_engine, persistence_bundle):
    provider = MockGnaniVoiceProvider()
    return AppointmentCoordinationWorkflow(
        brain=brain,
        policy_engine=policy_engine,
        appointment_repo=persistence_bundle.appointment_repo,
        voice_repo=persistence_bundle.voice_repo,
        voice_provider=provider,
    )


@pytest.fixture
def test_client(workflow, brain):
    settings = Settings(
        api_key="test_secret_key_123",
        api_auth_enabled=True,
        gnani_webhook_secret="gnani_webhook_secret_xyz",
        gnani_verification_enabled=True,
    )
    app = create_app(settings=settings, workflow=workflow, brain=brain)
    return TestClient(app)


# ------------------------------------------------------------------------------
# 1. Domain & Persistence Tests
# ------------------------------------------------------------------------------
def test_01_schema_v2_migration(temp_db):
    """Test that schema migrates cleanly to Version 2 with new tables."""
    store = SQLiteStore(temp_db, auto_init=True)
    try:
        ver_row = store.fetchone("SELECT MAX(version) AS ver FROM schema_version")
        assert ver_row is not None
        assert ver_row["ver"] == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 2

        # Verify new tables exist
        tables = store.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {t["name"] for t in tables}
        assert "appointments" in table_names
        assert "voice_call_records" in table_names
        assert "external_events" in table_names
    finally:
        store.close()


def test_02_appointment_persistence_roundtrip(persistence_bundle):
    """Test saving and retrieving an AppointmentRecord in SQLite."""
    repo = persistence_bundle.appointment_repo
    apt_id = f"apt_{uuid.uuid4().hex[:8]}"

    clinic = ClinicInfo(clinic_id="cln_apollo_01", clinic_name="Apollo Clinic Bangalore")
    doc = DoctorInfo(doctor_id="doc_sharma_01", doctor_name="Dr. Sharma", specialization="Cardiology")
    slot = AppointmentSlot(slot_id="slot_01", date="2026-10-20", start_time="10:00 AM", doctor_name="Dr. Sharma")

    record = AppointmentRecord(
        appointment_id=apt_id,
        request_id="req_test_01",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=clinic,
        doctor=doc,
        preferred_date="2026-10-20",
        preferred_time="10:00 AM",
        status=AppointmentStatus.SLOTS_RECEIVED,
        available_slots=[slot],
        approved_slot=slot,
        clinic_booking_reference="BK-12345",
        idempotency_key="idem_apt_01",
    )

    repo.save(record)

    # Retrieve by ID
    loaded = repo.get(apt_id)
    assert loaded is not None
    assert loaded.appointment_id == apt_id
    assert loaded.patient_id == "pat_rajesh_01"
    assert loaded.clinic.clinic_name == "Apollo Clinic Bangalore"
    assert loaded.doctor.doctor_name == "Dr. Sharma"
    assert loaded.status == AppointmentStatus.SLOTS_RECEIVED
    assert len(loaded.available_slots) == 1
    assert loaded.clinic_booking_reference == "BK-12345"

    # Retrieve by idempotency key
    by_idem = repo.get_by_idempotency_key("idem_apt_01")
    assert by_idem is not None
    assert by_idem.appointment_id == apt_id

    # List by patient
    pat_list = repo.list_by_patient("pat_rajesh_01")
    assert len(pat_list) >= 1
    assert any(a.appointment_id == apt_id for a in pat_list)


def test_03_voice_call_persistence_and_external_event_idempotency(persistence_bundle):
    """Test VoiceRepository persistence and duplicate external event rejection."""
    voice_repo = persistence_bundle.voice_repo
    apt_repo = persistence_bundle.appointment_repo

    # First save an appointment
    clinic = ClinicInfo(clinic_id="cln_01", clinic_name="Test Clinic")
    apt_record = AppointmentRecord(
        appointment_id="apt_vcall_test",
        request_id="req_vcall_test",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=clinic,
        preferred_date="2026-10-22",
    )
    apt_repo.save(apt_record)

    # Save voice call record
    call = VoiceCallRecord(
        call_id="call_01",
        external_call_id="gnani_call_101",
        appointment_id="apt_vcall_test",
        clinic_id="cln_01",
        clinic_name="Test Clinic",
        status=VoiceCallStatus.COMPLETED,
        disposition=VoiceCallDisposition.BOOKING_CONFIRMED,
        booking_outcome="CONFIRMED",
        booking_reference="BK-GNANI-999",
        idempotency_key="vck_unique_101",
    )
    voice_repo.save_call(call)

    loaded_call = voice_repo.get_by_external_id("gnani_call_101")
    assert loaded_call is not None
    assert loaded_call.booking_reference == "BK-GNANI-999"
    assert loaded_call.disposition == VoiceCallDisposition.BOOKING_CONFIRMED

    # Test external event idempotency
    first_record = voice_repo.record_external_event(
        event_id="ev_01",
        event_source="gnani",
        event_type="call_outcome",
        idempotency_key="gnani_idem_event_01",
        payload="{}",
    )
    assert first_record is True

    # Duplicate submission with identical idempotency_key must be rejected
    duplicate_record = voice_repo.record_external_event(
        event_id="ev_02",
        event_source="gnani",
        event_type="call_outcome",
        idempotency_key="gnani_idem_event_01",
        payload="{}",
    )
    assert duplicate_record is False


# ------------------------------------------------------------------------------
# 2. Authorization & Security Tests
# ------------------------------------------------------------------------------
def test_04_authorized_family_member_initiate(workflow):
    """Test authorized family member (Amit) can initiate appointment coordination."""
    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
        preferred_time="10:00 AM",
        reason_for_visit="Routine diabetes follow-up",
    )
    success, msg, record = workflow.initiate_coordination(req)
    assert success is True
    assert record is not None
    assert record.patient_id == "pat_rajesh_01"


def test_05_unauthorized_user_denied(workflow):
    """Test non-family member stranger is blocked from coordinating appointments."""
    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_stranger_99",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
    )
    success, msg, record = workflow.initiate_coordination(req)
    assert success is False
    assert "Unauthorized" in msg
    assert record is None


def test_06_unauthorized_family_member_booking_permission_denied(workflow):
    """Test family member with only view permissions cannot book/approve appointments."""
    # First create an appointment record awaiting approval
    clinic = ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic")
    slot = AppointmentSlot(slot_id="slot_cardio_01", date="2026-10-25", start_time="02:30 PM")
    record = AppointmentRecord(
        appointment_id="apt_approval_test",
        request_id="req_app_01",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=clinic,
        preferred_date="2026-10-25",
        status=AppointmentStatus.AWAITING_PATIENT_APPROVAL,
        available_slots=[slot],
    )
    workflow._save_record(record)

    # Priya has ["view_records", "check_medicine"], NOT ["approve_orders"]
    approval_req = AppointmentSlotApprovalRequest(
        appointment_id="apt_approval_test",
        approving_user_id="usr_priya_02",
        slot_id="slot_cardio_01",
    )
    success, msg, updated = workflow.approve_and_book_slot(approval_req)
    assert success is False
    assert "Unauthorized" in msg


# ------------------------------------------------------------------------------
# 3. Workflow Behavior Tests
# ------------------------------------------------------------------------------
def test_07_preferred_slot_available_workflow(workflow):
    """Workflow scenario: Preferred slot is available and matched."""
    # Configure mock provider to return preferred slot match
    workflow.voice_provider.set_scenario("availability_found_preferred")

    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
        preferred_time="10:00 AM",
    )
    success, msg, record = workflow.initiate_coordination(req)
    assert success is True
    assert record.status == AppointmentStatus.SLOTS_RECEIVED
    assert record.approved_slot is not None
    assert record.approved_slot.start_time == "10:00 AM"


def test_08_preferred_unavailable_requires_hitl_approval(workflow):
    """Workflow scenario: Preferred slot unavailable, alternative slots returned -> HITL approval required."""
    workflow.voice_provider.set_scenario("preferred_unavailable_alternatives")

    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
        preferred_time="09:00 AM",  # Morning unavailable
    )
    success, msg, record = workflow.initiate_coordination(req)
    assert success is True
    # Must NOT automatically book alternative; must await patient/caregiver approval!
    assert record.status == AppointmentStatus.AWAITING_PATIENT_APPROVAL
    assert len(record.available_slots) == 2
    assert record.approved_slot is None


def test_09_patient_approves_alternative_slot(workflow):
    """Workflow scenario: Caregiver explicitly approves one of the offered alternative slots."""
    workflow.voice_provider.set_scenario("preferred_unavailable_alternatives")

    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
        preferred_time="09:00 AM",
    )
    _, _, record = workflow.initiate_coordination(req)
    offered_slot = record.available_slots[0]

    # Amit approves slot
    app_req = AppointmentSlotApprovalRequest(
        appointment_id=record.appointment_id,
        approving_user_id="usr_amit_01",
        slot_id=offered_slot.slot_id,
    )
    success, msg, confirmed = workflow.approve_and_book_slot(app_req)
    assert success is True
    assert confirmed.status == AppointmentStatus.CONFIRMED
    assert confirmed.approved_slot.slot_id == offered_slot.slot_id
    assert confirmed.clinic_booking_reference is not None


def test_10_reject_unapproved_slot_selection(workflow):
    """Safety rule: Rejecting selection of a slot that was not offered by the clinic."""
    workflow.voice_provider.set_scenario("preferred_unavailable_alternatives")

    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
    )
    _, _, record = workflow.initiate_coordination(req)

    # Attempt to book a fake slot ID not offered
    app_req = AppointmentSlotApprovalRequest(
        appointment_id=record.appointment_id,
        approving_user_id="usr_amit_01",
        slot_id="slot_fake_invented_999",
    )
    success, msg, _ = workflow.approve_and_book_slot(app_req)
    assert success is False
    assert "Selection rejected" in msg or "not in the list" in msg


def test_11_dropped_call_sets_unknown_status(workflow):
    """Workflow scenario: Clinic call disconnected prematurely -> status set to UNKNOWN."""
    workflow.voice_provider.set_scenario("call_dropped")

    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
    )
    success, msg, record = workflow.initiate_coordination(req)
    assert success is True
    assert record.status == AppointmentStatus.UNKNOWN
    assert "dropped" in record.uncertainty_reason.lower()


def test_12_emergency_symptoms_bypass_scheduling(workflow):
    """Safety rule: Emergency symptoms must bypass routine appointment scheduling."""
    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic"),
        preferred_date="2026-10-25",
        reason_for_visit="Patient having severe chest pain and shortness of breath",
    )
    success, msg, record = workflow.initiate_coordination(req)
    assert success is False
    assert "emergency symptoms detected" in msg.lower()
    assert record is None


# ------------------------------------------------------------------------------
# 4. API Endpoints Tests
# ------------------------------------------------------------------------------
def test_13_api_health_endpoint(test_client):
    """Test GET /api/v1/health returns 200 with readiness data."""
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["schema_version"] == 2
    assert "appointment_workflow" in data["components"]


def test_14_api_create_appointment_success(test_client):
    """Test POST /api/v1/appointments with valid authentication."""
    payload = {
        "patient_id": "pat_rajesh_01",
        "requesting_user_id": "usr_amit_01",
        "clinic": {
            "clinic_id": "cln_city_01",
            "clinic_name": "City Health Clinic",
            "contact_phone": "+91-80-12345678",
        },
        "preferred_date": "2026-10-25",
        "preferred_time": "10:00 AM",
        "reason_for_visit": "General consultation",
    }
    response = test_client.post(
        "/api/v1/appointments",
        json=payload,
        headers={"X-API-Key": "test_secret_key_123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["patient_id"] == "pat_rajesh_01"
    assert "appointment_id" in data


def test_15_api_create_appointment_missing_auth(test_client):
    """Test POST /api/v1/appointments without API credentials returns 401."""
    payload = {
        "patient_id": "pat_rajesh_01",
        "requesting_user_id": "usr_amit_01",
        "clinic": {"clinic_id": "cln_01", "clinic_name": "City Clinic"},
        "preferred_date": "2026-10-25",
    }
    response = test_client.post("/api/v1/appointments", json=payload)
    assert response.status_code == 401


def test_16_api_create_appointment_emergency_rejected(test_client):
    """Test POST /api/v1/appointments with emergency symptoms returns 400."""
    payload = {
        "patient_id": "pat_rajesh_01",
        "requesting_user_id": "usr_amit_01",
        "clinic": {"clinic_id": "cln_01", "clinic_name": "City Clinic"},
        "preferred_date": "2026-10-25",
        "reason_for_visit": "Acute chest pain and severe bleeding",
    }
    response = test_client.post(
        "/api/v1/appointments",
        json=payload,
        headers={"X-API-Key": "test_secret_key_123"},
    )
    assert response.status_code == 400
    assert "emergency" in response.text.lower()


def test_17_api_get_appointment_authorized_vs_unauthorized(test_client, workflow):
    """Test GET /api/v1/appointments/{id} enforces family authorization."""
    # Pre-create an appointment
    clinic = ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic")
    apt = AppointmentRecord(
        appointment_id="apt_auth_test_101",
        request_id="req_auth_test",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=clinic,
        preferred_date="2026-10-28",
    )
    workflow._save_record(apt)

    # Amit is authorized
    resp_amit = test_client.get(
        "/api/v1/appointments/apt_auth_test_101",
        headers={"X-API-Key": "test_secret_key_123", "X-User-Id": "usr_amit_01"},
    )
    assert resp_amit.status_code == 200
    assert resp_amit.json()["appointment_id"] == "apt_auth_test_101"

    # Stranger is rejected with 403 Forbidden
    resp_stranger = test_client.get(
        "/api/v1/appointments/apt_auth_test_101",
        headers={"X-API-Key": "test_secret_key_123", "X-User-Id": "usr_stranger_99"},
    )
    assert resp_stranger.status_code == 403


def test_18_api_get_voice_context(test_client, workflow):
    """Test GET /api/v1/voice/appointments/{id}/context returns minimal non-sensitive data."""
    clinic = ClinicInfo(clinic_id="cln_01", clinic_name="Apollo Clinic")
    apt = AppointmentRecord(
        appointment_id="apt_vcontext_test",
        request_id="req_ctx",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=clinic,
        preferred_date="2026-10-30",
        preferred_time="11:00 AM",
    )
    workflow._save_record(apt)

    resp = test_client.get(
        "/api/v1/voice/appointments/apt_vcontext_test/context",
        headers={"X-API-Key": "test_secret_key_123", "X-User-Id": "usr_amit_01"},
    )
    assert resp.status_code == 200
    ctx = resp.json()
    assert ctx["appointment_id"] == "apt_vcontext_test"
    assert ctx["patient_display_name"] == "Rajesh Kumar"
    assert ctx["clinic_name"] == "Apollo Clinic"
    # Ensure sensitive clinical history is not exposed in voice context
    assert "chronic_conditions" not in ctx
    assert "allergies" not in ctx


def test_19_api_gnani_webhook_valid_and_duplicate(test_client, workflow):
    """Test POST /api/v1/integrations/gnani/call-outcome validates secret and enforces idempotency."""
    # Pre-create appointment
    clinic = ClinicInfo(clinic_id="cln_01", clinic_name="City Clinic")
    apt = AppointmentRecord(
        appointment_id="apt_webhook_test",
        request_id="req_wh",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=clinic,
        preferred_date="2026-10-30",
        status=AppointmentStatus.AVAILABILITY_PENDING,
    )
    workflow._save_record(apt)

    webhook_payload = {
        "external_call_id": "gnani_call_wh_1",
        "appointment_id": "apt_webhook_test",
        "status": "COMPLETED",
        "disposition": "BOOKING_CONFIRMED",
        "booking_confirmed": True,
        "booking_reference": "BK-GNANI-8888",
        "idempotency_key": "gnani_event_unique_wh_1",
        "metadata": {"duration_seconds": 45},
    }

    # Wrong webhook secret -> 401
    resp_bad_secret = test_client.post(
        "/api/v1/integrations/gnani/call-outcome",
        json=webhook_payload,
        headers={"X-Gnani-Secret": "wrong_secret"},
    )
    assert resp_bad_secret.status_code == 401

    # Correct webhook secret -> 200 OK
    resp_ok = test_client.post(
        "/api/v1/integrations/gnani/call-outcome",
        json=webhook_payload,
        headers={"X-Gnani-Secret": "gnani_webhook_secret_xyz"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["appointment"]["status"] == "CONFIRMED"
    assert resp_ok.json()["appointment"]["clinic_booking_reference"] == "BK-GNANI-8888"

    # Duplicate webhook call with same idempotency_key -> 200 OK (idempotent ignore)
    resp_duplicate = test_client.post(
        "/api/v1/integrations/gnani/call-outcome",
        json=webhook_payload,
        headers={"X-Gnani-Secret": "gnani_webhook_secret_xyz"},
    )
    assert resp_duplicate.status_code == 200
    assert "already processed" in resp_duplicate.json()["message"].lower()
