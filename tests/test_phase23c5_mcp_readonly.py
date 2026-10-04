"""Phase 23C.5 Tests: Dedicated Read-Only MCP Isolation Endpoint.

Validates that:
1. Read-only tools/list returns exactly two tools (get_appointment, get_voice_context).
2. get_appointment works for an authorized synthetic test case.
3. get_voice_context works for an authorized synthetic test case.
4. Unauthenticated calls are rejected with HTTP 401.
5. Unauthorized family access is rejected.
6. create_appointment is strictly rejected at router boundary.
7. approve_appointment_slot is strictly rejected at router boundary.
8. Unknown tool names are rejected.
9. Sensitive information remains redacted in voice context.
10. Existing full MCP endpoint still exposes its original four tools.
11. Database row counts remain unchanged during read-only tests.
"""

from __future__ import annotations

import json
import os
import tempfile
import sqlite3
import pytest
from fastapi.testclient import TestClient

from aarogya.config import Settings
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.policy.authorization_engine import PolicyAuthorizationEngine
from aarogya.workflows.appointment_coordination import AppointmentCoordinationWorkflow
from aarogya.connectors.gnani_adapter import MockGnaniVoiceProvider
from aarogya.persistence import get_persistence_bundle
from aarogya.models.appointment import AppointmentRecord, ClinicInfo
from aarogya.models.enums import AppointmentStatus
from aarogya.api.app import create_app
from aarogya.api.routes.mcp import MCP_TOOLS
from aarogya.api.routes.mcp_readonly import MCP_READONLY_TOOLS


API_KEY = "test_phase23c5_readonly_key"
AUTH_HEADERS = {"X-API-Key": API_KEY}


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
def seeded_appointment(workflow):
    """Seed a synthetic confirmed appointment for pat_rajesh_01 and usr_amit_01."""
    rec = AppointmentRecord(
        appointment_id="apt_test_readonly_01",
        request_id="req_test_01",
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(
            clinic_id="cln_apollo_blr",
            clinic_name="Apollo Clinic Bangalore",
            contact_phone="+91-80-23456789"
        ),
        preferred_date="2026-11-15",
        preferred_time="10:00 AM",
        status=AppointmentStatus.CONFIRMED,
        clinic_booking_reference="BK-READONLY-TEST-01"
    )
    workflow._save_record(rec)
    return rec


@pytest.fixture
def test_client(workflow):
    settings = Settings(
        api_auth_enabled=True,
        api_key=API_KEY,
        live_execution_enabled=False,
    )
    app = create_app(settings=settings, workflow=workflow)
    return TestClient(app)


# ------------------------------------------------------------------------------
# Test 1: Read-only tools/list returns read-only tools
# ------------------------------------------------------------------------------
def test_01_readonly_tools_list_count_and_names(test_client):
    # JSON-RPC tools/list
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    tools = data["result"]["tools"]
    tool_names = sorted([t["name"] for t in tools])
    assert tool_names == [
        "get_appointment",
        "get_household_inventory",
        "get_patient_medicines",
        "get_voice_context",
    ]
    assert len(tools) == 4

    # Liveness probe
    live_resp = test_client.get("/mcp/readonly")
    assert live_resp.status_code == 200
    live_data = live_resp.json()
    assert live_data["status"] == "ready"
    assert live_data["tool_count"] == 4

    # REST discovery
    rest_resp = test_client.get("/mcp/readonly/tools", headers=AUTH_HEADERS)
    assert rest_resp.status_code == 200
    assert len(rest_resp.json()["tools"]) == 4


# ------------------------------------------------------------------------------
# Test 2: get_appointment works for an authorized synthetic test case
# ------------------------------------------------------------------------------
def test_02_readonly_get_appointment_authorized(test_client, seeded_appointment):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_appointment",
                "arguments": {
                    "appointment_id": seeded_appointment.appointment_id,
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is False
    content = json.loads(body["result"]["content"][0]["text"])
    assert content["appointment_id"] == "apt_test_readonly_01"
    assert content["patient_id"] == "pat_rajesh_01"
    assert content["status"] == "CONFIRMED"
    assert content["clinic_booking_reference"] == "BK-READONLY-TEST-01"


# ------------------------------------------------------------------------------
# Test 3: get_voice_context works for an authorized synthetic test case
# ------------------------------------------------------------------------------
def test_03_readonly_get_voice_context_authorized(test_client, seeded_appointment):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_voice_context",
                "arguments": {
                    "appointment_id": seeded_appointment.appointment_id,
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is False
    content = json.loads(body["result"]["content"][0]["text"])
    assert content["appointment_id"] == "apt_test_readonly_01"
    assert content["patient_id"] == "pat_rajesh_01"
    assert content["patient_display_name"] == "Rajesh Kumar"
    assert content["clinic_name"] == "Apollo Clinic Bangalore"


# ------------------------------------------------------------------------------
# Test 4: Unauthenticated calls are rejected (HTTP 401)
# ------------------------------------------------------------------------------
def test_04_readonly_unauthenticated_rejected(test_client, seeded_appointment):
    # No auth header
    resp = test_client.post(
        "/mcp/readonly",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_appointment",
                "arguments": {"appointment_id": seeded_appointment.appointment_id},
            },
        },
    )
    assert resp.status_code == 401

    # Invalid auth header
    resp_invalid = test_client.post(
        "/mcp/readonly",
        headers={"X-API-Key": "wrong_key"},
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    )
    assert resp_invalid.status_code == 401


# ------------------------------------------------------------------------------
# Test 5: Unauthorized family access is rejected
# ------------------------------------------------------------------------------
def test_05_readonly_unauthorized_family_access_rejected(test_client, seeded_appointment):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_appointment",
                "arguments": {
                    "appointment_id": seeded_appointment.appointment_id,
                    "user_id": "usr_unauthorized_stranger",
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is True
    assert "Access denied" in body["result"]["content"][0]["text"]


# ------------------------------------------------------------------------------
# Test 6: create_appointment is rejected at router boundary
# ------------------------------------------------------------------------------
def test_06_readonly_create_appointment_rejected(test_client):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "create_appointment",
                "arguments": {
                    "patient_id": "pat_rajesh_01",
                    "requesting_user_id": "usr_amit_01",
                    "clinic_name": "Apollo Clinic",
                    "preferred_date": "2026-11-20",
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is True
    assert "strictly forbidden" in body["result"]["content"][0]["text"]


# ------------------------------------------------------------------------------
# Test 7: approve_appointment_slot is rejected at router boundary
# ------------------------------------------------------------------------------
def test_07_readonly_approve_slot_rejected(test_client, seeded_appointment):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "approve_appointment_slot",
                "arguments": {
                    "appointment_id": seeded_appointment.appointment_id,
                    "approving_user_id": "usr_amit_01",
                    "slot_id": "slot_01",
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is True
    assert "strictly forbidden" in body["result"]["content"][0]["text"]


# ------------------------------------------------------------------------------
# Test 8: Unknown tool names are rejected
# ------------------------------------------------------------------------------
def test_08_readonly_unknown_tool_rejected(test_client):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "random_unknown_tool",
                "arguments": {},
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is True
    assert "Unknown tool" in body["result"]["content"][0]["text"]


# ------------------------------------------------------------------------------
# Test 9: Sensitive information remains redacted
# ------------------------------------------------------------------------------
def test_09_readonly_sensitive_data_omitted(test_client, seeded_appointment):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "get_voice_context",
                "arguments": {
                    "appointment_id": seeded_appointment.appointment_id,
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    raw_text = resp.json()["result"]["content"][0]["text"]
    # Verify clinical medical conditions and allergies are NOT leaked in voice context
    assert "Hypertension" not in raw_text
    assert "Diabetes" not in raw_text
    assert "Penicillin" not in raw_text


# ------------------------------------------------------------------------------
# Test 10: Existing full MCP endpoint still exposes its original four tools
# ------------------------------------------------------------------------------
def test_10_full_mcp_endpoint_intact(test_client):
    resp = test_client.post(
        "/mcp",
        headers=AUTH_HEADERS,
        json={"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    tool_names = sorted([t["name"] for t in tools])
    assert tool_names == [
        "approve_appointment_slot",
        "create_appointment",
        "get_appointment",
        "get_voice_context",
    ]
    assert len(tools) == 4


# ------------------------------------------------------------------------------
# Test 11 & 12: Database row counts remain unchanged during read-only calls
# ------------------------------------------------------------------------------
def test_11_database_row_counts_unchanged_during_readonly_operations(test_client, seeded_appointment, temp_db):
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    counts_before = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()

    # Execute read operations
    for _ in range(5):
        test_client.post(
            "/mcp/readonly",
            headers=AUTH_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 100,
                "method": "tools/call",
                "params": {
                    "name": "get_appointment",
                    "arguments": {
                        "appointment_id": seeded_appointment.appointment_id,
                        "user_id": "usr_amit_01",
                    },
                },
            },
        )
        test_client.post(
            "/mcp/readonly",
            headers=AUTH_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 101,
                "method": "tools/call",
                "params": {
                    "name": "get_voice_context",
                    "arguments": {
                        "appointment_id": seeded_appointment.appointment_id,
                        "user_id": "usr_amit_01",
                    },
                },
            },
        )

    # Attempt rejected mutation operations
    test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "create_appointment",
                "arguments": {
                    "patient_id": "pat_rajesh_01",
                    "requesting_user_id": "usr_amit_01",
                    "clinic_name": "New Clinic",
                    "preferred_date": "2026-12-01",
                },
            },
        },
    )

    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    counts_after = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()

    assert counts_before == counts_after, f"Counts changed! Before: {counts_before}, After: {counts_after}"


# ------------------------------------------------------------------------------
# Test 12: Amit can retrieve Rajesh's medicine information
# ------------------------------------------------------------------------------
def test_12_readonly_get_patient_medicines_rajesh(test_client):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "get_patient_medicines",
                "arguments": {
                    "patient_id": "pat_rajesh_01",
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp.status_code == 200
    res = resp.json()["result"]
    assert res["isError"] is False
    content = json.loads(res["content"][0]["text"])
    assert content["patient_id"] == "pat_rajesh_01"
    assert content["patient_name"] == "Rajesh Kumar"
    assert "Medicine X" in [p["medicine_name"] for p in content["medicine_plans"]]
    assert len(content["prescriptions"]) >= 1


# ------------------------------------------------------------------------------
# Test 13: Amit can retrieve Sunita's medicines and resolve relationships
# ------------------------------------------------------------------------------
def test_13_readonly_get_patient_medicines_sunita_and_relationships(test_client):
    # Query with ID
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "get_patient_medicines",
                "arguments": {
                    "patient_id": "pat_sunita_02",
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp.status_code == 200
    res = resp.json()["result"]
    assert res["isError"] is False
    content = json.loads(res["content"][0]["text"])
    assert content["patient_id"] == "pat_sunita_02"
    assert content["patient_name"] == "Sunita Kumar"
    assert "Hypothyroidism" in content["chronic_conditions"]
    assert any(p["medicine_name"] == "Thyronorm" and p["current_inventory_count"] == 25 for p in content["inventory_status"])

    # Query with relationship "my mother"
    resp_rel = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 131,
            "method": "tools/call",
            "params": {
                "name": "get_patient_medicines",
                "arguments": {
                    "patient_id": "my mother",
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp_rel.status_code == 200
    res_rel = resp_rel.json()["result"]
    assert res_rel["isError"] is False
    content_rel = json.loads(res_rel["content"][0]["text"])
    assert content_rel["patient_id"] == "pat_sunita_02"

    # Query with relationship "my father"
    resp_rel_father = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 132,
            "method": "tools/call",
            "params": {
                "name": "get_patient_medicines",
                "arguments": {
                    "patient_id": "my father",
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp_rel_father.status_code == 200
    res_rel_father = resp_rel_father.json()["result"]
    assert res_rel_father["isError"] is False
    content_father = json.loads(res_rel_father["content"][0]["text"])
    assert content_father["patient_id"] == "pat_rajesh_01"


# ------------------------------------------------------------------------------
# Test 14: Amit can retrieve household inventory
# ------------------------------------------------------------------------------
def test_14_readonly_get_household_inventory(test_client):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "get_household_inventory",
                "arguments": {
                    "user_id": "usr_amit_01",
                },
            },
        },
    )
    assert resp.status_code == 200
    res = resp.json()["result"]
    assert res["isError"] is False
    content = json.loads(res["content"][0]["text"])
    assert content["authorized_patients_count"] >= 2
    patient_ids = [p["patient_id"] for p in content["household_inventory"]]
    assert "pat_rajesh_01" in patient_ids
    assert "pat_sunita_02" in patient_ids


# ------------------------------------------------------------------------------
# Test 15: Unauthorized family access is rejected
# ------------------------------------------------------------------------------
def test_15_readonly_medicine_unauthorized_rejected(test_client):
    resp = test_client.post(
        "/mcp/readonly",
        headers=AUTH_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "get_patient_medicines",
                "arguments": {
                    "patient_id": "pat_sunita_02",
                    "user_id": "usr_stranger_99",
                },
            },
        },
    )
    assert resp.status_code == 200
    res = resp.json()["result"]
    assert res["isError"] is True
    assert "Access denied" in res["content"][0]["text"]
