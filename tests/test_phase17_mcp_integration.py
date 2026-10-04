"""Phase 17 Tests: Model Context Protocol (MCP) Integration for Aarogya Platform."""

from __future__ import annotations

import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from aarogya.config import Settings
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.policy.authorization_engine import PolicyAuthorizationEngine
from aarogya.workflows.appointment_coordination import AppointmentCoordinationWorkflow
from aarogya.connectors.gnani_adapter import MockGnaniVoiceProvider
from aarogya.persistence import get_persistence_bundle
from aarogya.models.enums import AppointmentStatus
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
def voice_provider():
    return MockGnaniVoiceProvider()


@pytest.fixture
def workflow(brain, policy_engine, persistence_bundle, voice_provider):
    return AppointmentCoordinationWorkflow(
        brain=brain,
        policy_engine=policy_engine,
        appointment_repo=persistence_bundle.appointment_repo,
        voice_repo=persistence_bundle.voice_repo,
        voice_provider=voice_provider,
    )


@pytest.fixture
def test_client(workflow, brain):
    settings = Settings(
        api_key="mcp_secret_key_999",
        api_auth_enabled=True,
    )
    app = create_app(settings=settings, workflow=workflow, brain=brain)
    return TestClient(app)


AUTH_HEADERS = {"X-API-Key": "mcp_secret_key_999"}
BEARER_HEADERS = {"Authorization": "Bearer mcp_secret_key_999"}


# ------------------------------------------------------------------------------
# 1. MCP Protocol Handshake, Liveness Probe & Tools Discovery Tests
# ------------------------------------------------------------------------------
def test_mcp_get_liveness_probe(test_client):
    """GET /mcp and GET /api/v1/mcp return HTTP 200 with minimal liveness info."""
    for path in ("/mcp", "/api/v1/mcp"):
        resp = test_client.get(path)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["server"] == "aarogya-coordination-api"
        assert data["protocol_version"] == "2024-11-05"
        assert data["transport"] == "http-jsonrpc"
        assert "capabilities" in data


def test_mcp_head_liveness_probe(test_client):
    """HEAD /mcp and HEAD /api/v1/mcp return HTTP 200 with empty body."""
    for path in ("/mcp", "/api/v1/mcp"):
        resp = test_client.head(path)
        assert resp.status_code == 200
        assert resp.text == ""


def test_mcp_get_liveness_zero_sensitive_data(test_client):
    """GET /mcp must never leak credentials, secrets, or patient/appointment data."""
    resp = test_client.get("/mcp")
    assert resp.status_code == 200
    raw_text = resp.text.lower()
    for forbidden in ["patient", "appointment", "secret", "key", "password", "token", "diagnostic", "vitals"]:
        assert forbidden not in raw_text


def test_mcp_initialize(test_client):
    """MCP JSON-RPC initialize handshake returns protocol capabilities."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agenticorg", "version": "0.3.0"},
        },
    }
    resp = test_client.post("/api/v1/mcp", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in data["result"]["capabilities"]
    assert data["result"]["serverInfo"]["name"] == "aarogya-coordination-api"


def test_mcp_tools_list_jsonrpc(test_client):
    """MCP JSON-RPC tools/list returns exactly the 4 authorized tools."""
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    resp = test_client.post("/api/v1/mcp", json=payload, headers=BEARER_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    assert "create_appointment" in tool_names
    assert "get_appointment" in tool_names
    assert "get_voice_context" in tool_names
    assert "approve_appointment_slot" in tool_names
    # Gnani webhook must never be exposed as an agent tool
    assert "record_voice_outcome" not in tool_names
    assert len(tools) == 4


def test_mcp_tools_list_rest_compatibility(test_client):
    """Direct REST GET /mcp/tools is compatible with AgenticOrg SDK client."""
    resp = test_client.get("/api/v1/mcp/tools", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    tools = resp.json().get("tools", [])
    assert len(tools) == 4


# ------------------------------------------------------------------------------
# 2. Authentication & Authorization Guard Tests
# ------------------------------------------------------------------------------
def test_mcp_unauthenticated_request_rejected(test_client):
    """Unauthenticated MCP requests must fail with 401."""
    payload = {"jsonrpc": "2.0", "id": 10, "method": "tools/list"}
    resp = test_client.post("/api/v1/mcp", json=payload)
    assert resp.status_code == 401


def test_mcp_invalid_api_key_rejected(test_client):
    """Invalid credentials must fail with 401."""
    payload = {"jsonrpc": "2.0", "id": 11, "method": "tools/list"}
    resp = test_client.post("/api/v1/mcp", json=payload, headers={"X-API-Key": "wrong_key"})
    assert resp.status_code == 401


# ------------------------------------------------------------------------------
# 3. Tool Execution: create_appointment & Emergency Detection
# ------------------------------------------------------------------------------
def test_mcp_create_appointment_success(test_client):
    """Authorized caregiver creates appointment successfully via MCP JSON-RPC."""
    payload = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "create_appointment",
            "arguments": {
                "patient_id": "pat_rajesh_01",
                "requesting_user_id": "usr_amit_01",
                "clinic_name": "Apollo Clinic Indiranagar",
                "preferred_date": "2026-10-15",
                "reason_for_visit": "Routine hypertension review",
                "idempotency_key": "mcp_create_001",
            },
        },
    }
    resp = test_client.post("/api/v1/mcp", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["isError"] is False
    content_text = json.loads(result["content"][0]["text"])
    assert content_text["patient_id"] == "pat_rajesh_01"
    assert "appointment_id" in content_text


def test_mcp_create_appointment_emergency_rejected(test_client):
    """Emergency symptoms must immediately reject coordination with safety guidance."""
    payload = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {
            "name": "create_appointment",
            "arguments": {
                "patient_id": "pat_rajesh_01",
                "requesting_user_id": "usr_amit_01",
                "clinic_name": "Apollo Clinic",
                "preferred_date": "2026-10-15",
                "reason_for_visit": "Severe chest pain and shortness of breath",
            },
        },
    }
    resp = test_client.post("/api/v1/mcp", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["isError"] is True
    err_text = result["content"][0]["text"].lower()
    assert "emergency" in err_text or "immediate" in err_text


def test_mcp_create_appointment_unauthorized_user(test_client):
    """Unauthorized user requesting appointment for stranger must fail-closed."""
    payload = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "create_appointment",
            "arguments": {
                "patient_id": "pat_rajesh_01",
                "requesting_user_id": "usr_stranger_99",
                "clinic_name": "Apollo Clinic",
                "preferred_date": "2026-10-15",
                "reason_for_visit": "Consultation",
            },
        },
    }
    resp = test_client.post("/api/v1/mcp", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["isError"] is True
    assert "unauthorized" in result["content"][0]["text"].lower() or "denied" in result["content"][0]["text"].lower()


# ------------------------------------------------------------------------------
# 4. Tool Execution: get_appointment & get_voice_context
# ------------------------------------------------------------------------------
def test_mcp_get_appointment_and_voice_context(test_client):
    """Retrieve appointment and verify minimal non-sensitive voice context."""
    # 1. Create appointment
    create_payload = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "create_appointment",
            "arguments": {
                "patient_id": "pat_rajesh_01",
                "requesting_user_id": "usr_amit_01",
                "clinic_name": "Apollo Clinic",
                "preferred_date": "2026-10-15",
                "reason_for_visit": "Diabetic follow up",
            },
        },
    }
    create_resp = test_client.post("/api/v1/mcp", json=create_payload, headers=AUTH_HEADERS)
    appt_data = json.loads(create_resp.json()["result"]["content"][0]["text"])
    appt_id = appt_data["appointment_id"]

    # 2. Get appointment
    get_payload = {
        "jsonrpc": "2.0",
        "id": 31,
        "method": "tools/call",
        "params": {
            "name": "get_appointment",
            "arguments": {
                "appointment_id": appt_id,
                "user_id": "usr_amit_01",
            },
        },
    }
    get_resp = test_client.post("/api/v1/mcp", json=get_payload, headers=AUTH_HEADERS)
    assert get_resp.status_code == 200
    get_result = get_resp.json()["result"]
    assert get_result["isError"] is False
    rec = json.loads(get_result["content"][0]["text"])
    assert rec["appointment_id"] == appt_id

    # 3. Get voice context (Must expose strictly non-sensitive fields)
    vc_payload = {
        "jsonrpc": "2.0",
        "id": 32,
        "method": "tools/call",
        "params": {
            "name": "get_voice_context",
            "arguments": {
                "appointment_id": appt_id,
                "user_id": "usr_amit_01",
            },
        },
    }
    vc_resp = test_client.post("/api/v1/mcp", json=vc_payload, headers=AUTH_HEADERS)
    assert vc_resp.status_code == 200
    vc_result = vc_resp.json()["result"]
    assert vc_result["isError"] is False
    vcontext = json.loads(vc_result["content"][0]["text"])
    assert vcontext["appointment_id"] == appt_id
    assert "patient_id" in vcontext
    # Verify no sensitive clinical fields are leaked
    assert "medications" not in vcontext
    assert "diagnoses" not in vcontext
    assert "patient_display_name" in vcontext
    assert "clinic_name" in vcontext
    assert "status" in vcontext


def test_mcp_get_appointment_unauthorized_fails(test_client):
    """Unauthorized user cannot read another family's appointment."""
    # 1. Create appointment
    create_payload = {
        "name": "create_appointment",
        "arguments": {
            "patient_id": "pat_rajesh_01",
            "requesting_user_id": "usr_amit_01",
            "clinic_name": "Apollo Clinic",
            "preferred_date": "2026-10-15",
            "reason_for_visit": "Checkup",
        },
    }
    create_resp = test_client.post("/api/v1/mcp/call", json=create_payload, headers=AUTH_HEADERS)
    appt_id = create_resp.json()["output"]["appointment_id"]

    # 2. Strangers attempt to read
    get_payload = {
        "name": "get_appointment",
        "arguments": {
            "appointment_id": appt_id,
            "user_id": "usr_stranger_99",
        },
    }
    get_resp = test_client.post("/api/v1/mcp/call", json=get_payload, headers=AUTH_HEADERS)
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["success"] is False
    assert "access denied" in data["error"].lower()


# ------------------------------------------------------------------------------
# 5. Tool Execution: approve_appointment_slot & Caregiver Authorization
# ------------------------------------------------------------------------------
def test_mcp_approve_appointment_slot_flow(test_client, voice_provider):
    """Caregiver approves offered slot and transitions appointment to CONFIRMED."""
    # Trigger scenario where preferred slot is unavailable and alternative slots are returned for HITL approval
    voice_provider.set_scenario("preferred_unavailable_alternatives")

    # 1. Create appointment
    create_payload = {
        "name": "create_appointment",
        "arguments": {
            "patient_id": "pat_rajesh_01",
            "requesting_user_id": "usr_amit_01",
            "clinic_name": "Apollo Clinic",
            "preferred_date": "2026-10-15",
            "preferred_time": "09:00 AM",
            "reason_for_visit": "Cardiology consultation",
        },
    }
    create_resp = test_client.post("/api/v1/mcp/call", json=create_payload, headers=AUTH_HEADERS)
    appt_rec = create_resp.json()["output"]
    appt_id = appt_rec["appointment_id"]
    available_slots = appt_rec.get("available_slots") or []

    assert len(available_slots) > 0, "Workflow should have offered clinic alternative slots"
    slot_id = available_slots[0]["slot_id"]

    # 2. Caregiver approves slot
    approve_payload = {
        "name": "approve_appointment_slot",
        "arguments": {
            "appointment_id": appt_id,
            "approving_user_id": "usr_amit_01",
            "slot_id": slot_id,
            "approval_notes": "Caregiver approved morning slot",
            "idempotency_key": f"mcp_approve_{appt_id}",
        },
    }
    approve_resp = test_client.post("/api/v1/mcp/call", json=approve_payload, headers=AUTH_HEADERS)
    assert approve_resp.status_code == 200
    approve_data = approve_resp.json()
    assert approve_data["success"] is True
    assert approve_data["output"]["status"] == "CONFIRMED"
    assert approve_data["output"]["approved_slot"]["slot_id"] == slot_id

    # 3. Idempotent re-approval with same key succeeds safely
    reapprove_resp = test_client.post("/api/v1/mcp/call", json=approve_payload, headers=AUTH_HEADERS)
    assert reapprove_resp.status_code == 200
    assert reapprove_resp.json()["success"] is True
    assert reapprove_resp.json()["output"]["status"] == "CONFIRMED"


def test_mcp_approve_slot_unauthorized_caregiver_rejected(test_client, voice_provider):
    """Unauthorized user cannot approve an appointment slot."""
    voice_provider.set_scenario("preferred_unavailable_alternatives")

    # 1. Create appointment
    create_payload = {
        "name": "create_appointment",
        "arguments": {
            "patient_id": "pat_rajesh_01",
            "requesting_user_id": "usr_amit_01",
            "clinic_name": "Apollo Clinic",
            "preferred_date": "2026-10-15",
            "preferred_time": "09:00 AM",
            "reason_for_visit": "Consultation",
        },
    }
    create_resp = test_client.post("/api/v1/mcp/call", json=create_payload, headers=AUTH_HEADERS)
    appt_rec = create_resp.json()["output"]
    appt_id = appt_rec["appointment_id"]
    slot_id = appt_rec["available_slots"][0]["slot_id"]

    # 2. Unauthorized stranger attempts to approve
    approve_payload = {
        "name": "approve_appointment_slot",
        "arguments": {
            "appointment_id": appt_id,
            "approving_user_id": "usr_stranger_99",
            "slot_id": slot_id,
        },
    }
    approve_resp = test_client.post("/api/v1/mcp/call", json=approve_payload, headers=AUTH_HEADERS)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["success"] is False
    assert "unauthorized" in approve_resp.json()["error"].lower() or "lacks" in approve_resp.json()["error"].lower()


# ------------------------------------------------------------------------------
# 6. Malformed & Unknown Method Handling
# ------------------------------------------------------------------------------
def test_mcp_unknown_method(test_client):
    """Unknown JSON-RPC method returns -32601."""
    payload = {"jsonrpc": "2.0", "id": 99, "method": "non_existent_method"}
    resp = test_client.post("/api/v1/mcp", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    err = resp.json()["error"]
    assert err["code"] == -32601


def test_mcp_unknown_tool(test_client):
    """Calling an un-allowlisted tool returns error."""
    payload = {
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {"name": "unauthorized_arbitrary_tool", "arguments": {}},
    }
    resp = test_client.post("/api/v1/mcp", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["isError"] is True
    assert "unknown tool" in result["content"][0]["text"].lower()
