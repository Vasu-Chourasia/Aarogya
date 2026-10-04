"""Tests for Module 7: AgenticOrg Authentication & Tenant Discovery (Section 11)."""

from __future__ import annotations

import io
import sys
from typing import Dict, Any, List
from unittest.mock import MagicMock

import httpx
import pytest

from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.cli import handle_agenticorg_status
from aarogya.config import Settings, ExecutionMode
from aarogya.connectors.agenticorg_discovery import AgenticOrgDiscoveryService
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.models.enums import (
    AgenticOrgAuthState,
    DiscoveryStatus,
    AuditEventType,
)
from aarogya.orchestrator.audit_logger import AuditLogger


# ------------------------------------------------------------------------------
# Mock Client Helper
# ------------------------------------------------------------------------------
class MockAgenticOrgClient:
    """Mock AgenticOrg SDK client with instrumented calls."""

    def __init__(
        self,
        connectors_data: List[Dict[str, Any]] | Exception = None,
        mcp_data: List[Dict[str, Any]] | Exception = None,
    ):
        self.connectors_data = connectors_data if connectors_data is not None else []
        self.mcp_data = mcp_data if mcp_data is not None else []

        self.connectors = MagicMock()
        self.mcp = MagicMock()
        self.agents = MagicMock()
        self.workflows = MagicMock()

        # Connectors list behavior
        if isinstance(self.connectors_data, Exception):
            self.connectors.list.side_effect = self.connectors_data
        else:
            self.connectors.list.return_value = self.connectors_data

        # MCP tools behavior
        if isinstance(self.mcp_data, Exception):
            self.mcp.tools.side_effect = self.mcp_data
        else:
            self.mcp.tools.return_value = self.mcp_data

        # Explicitly spy on execution endpoints to verify they are never invoked
        self.mcp.call = MagicMock(side_effect=AssertionError("CRITICAL: mcp.call must never be called during discovery!"))
        self.agents.run = MagicMock(side_effect=AssertionError("CRITICAL: agents.run must never be called during discovery!"))
        self.workflows.run = MagicMock(side_effect=AssertionError("CRITICAL: workflows.run must never be called during discovery!"))


# ==============================================================================
# Test 1: Missing API key
# ==============================================================================
def test_scenario_1_missing_api_key():
    settings = Settings(
        agenticorg_api_key="",
        agenticorg_grantex_token="",
        execution_mode=ExecutionMode.SIMULATION,
    )
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    has_creds, reason = service.check_credentials()
    assert has_creds is False
    assert service.auth_state == AgenticOrgAuthState.NOT_CONFIGURED
    assert "not configured" in reason.lower()

    # Verify audit event
    events = [e.event_type for e in audit_logger.get_all_entries()]
    assert AuditEventType.CREDENTIALS_MISSING in events


# ==============================================================================
# Test 2: SDK initialization failure
# ==============================================================================
def test_scenario_2_sdk_initialization_failure():
    settings = Settings(
        agenticorg_api_key="valid_looking_key",
        agenticorg_base_url="invalid://url::bad",
    )
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    # Initialize client will fail cleanly without crashing
    client, err = service.initialize_client()
    # Either client is None or err is recorded
    if client is None:
        assert err is not None
        assert service.auth_state in (AgenticOrgAuthState.CONNECTION_FAILED, AgenticOrgAuthState.NOT_CONFIGURED)


# ==============================================================================
# Test 3: Authentication success
# ==============================================================================
def test_scenario_3_authentication_success():
    settings = Settings(agenticorg_api_key="valid_test_key")
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    mock_client = MockAgenticOrgClient(connectors_data=[{"id": "conn_1", "name": "Pharmacy API"}])
    is_auth, state, msg = service.verify_authentication(mock_client)

    assert is_auth is True
    assert state == AgenticOrgAuthState.AUTHENTICATED
    assert service.auth_state == AgenticOrgAuthState.AUTHENTICATED
    assert "confirmed" in msg.lower()

    events = [e.event_type for e in audit_logger.get_all_entries()]
    assert AuditEventType.AUTHENTICATION_SUCCEEDED in events


# ==============================================================================
# Test 4: Authentication failure (HTTP 401/403)
# ==============================================================================
def test_scenario_4_authentication_failure():
    settings = Settings(agenticorg_api_key="invalid_expired_key")
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    req = httpx.Request("GET", "https://app.agenticorg.ai/api/v1/connectors")
    resp = httpx.Response(status_code=401, text="Unauthorized: Invalid API key", request=req)
    http_err = httpx.HTTPStatusError("401 Unauthorized", request=req, response=resp)

    mock_client = MockAgenticOrgClient(connectors_data=http_err)
    is_auth, state, msg = service.verify_authentication(mock_client)

    assert is_auth is False
    assert state == AgenticOrgAuthState.AUTH_FAILED
    assert service.auth_state == AgenticOrgAuthState.AUTH_FAILED
    assert "401" in msg

    events = [e.event_type for e in audit_logger.get_all_entries()]
    assert AuditEventType.AUTHENTICATION_FAILED in events


# ==============================================================================
# Test 5: Authentication timeout
# ==============================================================================
def test_scenario_5_authentication_timeout():
    settings = Settings(agenticorg_api_key="valid_key", agenticorg_discovery_timeout_seconds=2.0)
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    req = httpx.Request("GET", "https://app.agenticorg.ai/api/v1/connectors")
    timeout_err = httpx.TimeoutException("Read timed out after 2.0s", request=req)

    mock_client = MockAgenticOrgClient(connectors_data=timeout_err)
    is_auth, state, msg = service.verify_authentication(mock_client)

    assert is_auth is False
    assert state == AgenticOrgAuthState.TIMEOUT
    assert service.auth_state == AgenticOrgAuthState.TIMEOUT
    assert "timed out" in msg.lower()


# ==============================================================================
# Test 6: Unsupported authentication method
# ==============================================================================
def test_scenario_6_unsupported_authentication_method():
    settings = Settings(agenticorg_api_key="valid_key")
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    # Incompatible client lacking connectors resource
    class IncompatibleClient:
        pass

    incompatible_client = IncompatibleClient()
    is_auth, state, msg = service.verify_authentication(incompatible_client)

    assert is_auth is False
    assert state == AgenticOrgAuthState.UNSUPPORTED
    assert "lacks expected" in msg.lower()


# ==============================================================================
# Test 7: Connector discovery success
# ==============================================================================
def test_scenario_7_connector_discovery_success():
    settings = Settings(agenticorg_api_key="valid_key")
    registry = ConnectorRegistry()
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, registry=registry, audit_logger=audit_logger)

    connectors = [
        {
            "id": "conn_apollo_01",
            "name": "Apollo Direct Pharmacy",
            "provider": "Apollo Pharmacy API",
            "status": "active",
            "capabilities": ["check_medicine_availability"],
        },
        {
            "id": "conn_task_01",
            "name": "Caregiver Task Backend",
            "provider": "Aarogya Engine",
            "status": "active",
            "capabilities": ["create_caregiver_task"],
        },
    ]

    mock_client = MockAgenticOrgClient(connectors_data=connectors, mcp_data=[])
    report = service.discover_tenant(client=mock_client)

    assert report["discovery_status"] == DiscoveryStatus.SUCCESS.value
    assert report["registered_connectors_count"] == 2
    assert "conn_apollo_01" in service.discovered_connectors
    assert "conn_task_01" in service.discovered_connectors

    # Check normalized status in registry
    pharmacy_conn = registry.get_connector_status("pharmacy")
    assert pharmacy_conn is not None
    assert pharmacy_conn.registered is True
    assert pharmacy_conn.connected is True
    assert pharmacy_conn.discovery_source == "agenticorg_connectors"


# ==============================================================================
# Test 8: MCP discovery success
# ==============================================================================
def test_scenario_8_mcp_discovery_success():
    settings = Settings(agenticorg_api_key="valid_key")
    registry = ConnectorRegistry()
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, registry=registry, audit_logger=audit_logger)

    mcp_tools = [
        {"name": "check_pharmacy_inventory", "description": "Inspect live pharmacy inventory"},
        {"name": "query_doctor_availability", "description": "Lookup clinical provider slots"},
    ]

    mock_client = MockAgenticOrgClient(connectors_data=[], mcp_data=mcp_tools)
    report = service.discover_tenant(client=mock_client)

    assert report["discovery_status"] == DiscoveryStatus.SUCCESS.value
    assert report["mcp_tools_count"] == 2
    assert len(service.discovered_mcp_tools) == 2

    # Check registered MCP status
    mcp_tool_conn = registry.get_connector_status("mcp:check_pharmacy_inventory")
    assert mcp_tool_conn is not None
    assert mcp_tool_conn.registered is True
    assert mcp_tool_conn.capable is True
    assert mcp_tool_conn.discovery_source == "agenticorg_mcp"


# ==============================================================================
# Test 9: Partial discovery (Connectors OK, MCP fails)
# ==============================================================================
def test_scenario_9_partial_discovery():
    settings = Settings(agenticorg_api_key="valid_key")
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    connectors = [{"id": "conn_1", "name": "Pharmacy API", "status": "active"}]
    mock_client = MockAgenticOrgClient(
        connectors_data=connectors,
        mcp_data=Exception("MCP server 503 unavailable"),
    )

    report = service.discover_tenant(client=mock_client)

    assert report["discovery_status"] == DiscoveryStatus.PARTIAL.value
    assert report["registered_connectors_count"] == 1
    assert report["mcp_tools_count"] == 0
    assert len(report["errors"]) > 0
    assert any("MCP discovery failed" in err for err in report["errors"])

    events = [e.event_type for e in audit_logger.get_all_entries()]
    assert AuditEventType.PARTIAL_DISCOVERY in events


# ==============================================================================
# Test 10: Discovery API failure (500 error not masked as empty catalog)
# ==============================================================================
def test_scenario_10_discovery_api_failure():
    settings = Settings(agenticorg_api_key="valid_key")
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    req = httpx.Request("GET", "https://app.agenticorg.ai/api/v1/connectors")
    resp = httpx.Response(status_code=500, text="Internal Server Error", request=req)
    http_err = httpx.HTTPStatusError("500 Server Error", request=req, response=resp)

    mock_client = MockAgenticOrgClient(connectors_data=http_err, mcp_data=[])
    report = service.discover_tenant(client=mock_client)

    assert report["discovery_status"] == DiscoveryStatus.FAILED.value
    assert len(report["errors"]) > 0
    assert "500" in report["errors"][0]


# ==============================================================================
# Test 11: Empty but valid tenant catalog
# ==============================================================================
def test_scenario_11_empty_valid_catalog():
    settings = Settings(agenticorg_api_key="valid_key")
    audit_logger = AuditLogger(log_file=None)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    # Empty list returned from valid 200 response
    mock_client = MockAgenticOrgClient(connectors_data=[], mcp_data=[])
    report = service.discover_tenant(client=mock_client)

    assert report["discovery_status"] == DiscoveryStatus.SUCCESS.value
    assert report["registered_connectors_count"] == 0
    assert report["mcp_tools_count"] == 0
    assert len(report["errors"]) == 0


# ==============================================================================
# Test 12: Unknown authorization state remains unknown (None)
# ==============================================================================
def test_scenario_12_unknown_authorization_remains_unknown():
    settings = Settings(agenticorg_api_key="valid_key")
    service = AgenticOrgDiscoveryService(settings=settings)

    # Connector without explicit authorization permissions
    item = {"id": "conn_unverified", "name": "Generic Provider", "status": "active"}
    status = service._normalize_connector(item)

    assert status.registered is True
    assert status.authorized is None  # Must remain unknown/None, NOT True!


# ==============================================================================
# Test 13: Discovery does not invoke execution tools
# ==============================================================================
def test_scenario_13_discovery_does_not_invoke_execution_tools():
    settings = Settings(agenticorg_api_key="valid_key")
    service = AgenticOrgDiscoveryService(settings=settings)

    mock_client = MockAgenticOrgClient(
        connectors_data=[{"id": "conn_1", "name": "Pharmacy API"}],
        mcp_data=[{"name": "place_pharmacy_order"}],
    )

    report = service.discover_tenant(client=mock_client)
    assert report["safety_boundary_verified"] is True

    # Assert that execution endpoints were NEVER called
    mock_client.mcp.call.assert_not_called()
    mock_client.agents.run.assert_not_called()
    mock_client.workflows.run.assert_not_called()


# ==============================================================================
# Test 14: Discovery does not mutate Family Health Brain
# ==============================================================================
def test_scenario_14_discovery_does_not_mutate_brain():
    brain = FamilyHealthBrain(seed_fictional_data=True)
    initial_rajesh = brain.get_patient("pat_rajesh_01")
    initial_prescriptions_count = len(initial_rajesh.prescriptions)
    initial_plans_count = len(initial_rajesh.medicine_plans)

    settings = Settings(agenticorg_api_key="valid_key")
    service = AgenticOrgDiscoveryService(settings=settings)

    mock_client = MockAgenticOrgClient(
        connectors_data=[{"id": "conn_pharmacy", "name": "Pharmacy"}],
        mcp_data=[{"name": "order_med"}],
    )
    service.discover_tenant(client=mock_client)

    # Check brain is completely untouched
    after_rajesh = brain.get_patient("pat_rajesh_01")
    assert len(after_rajesh.prescriptions) == initial_prescriptions_count
    assert len(after_rajesh.medicine_plans) == initial_plans_count


# ==============================================================================
# Test 15: Secrets are absent from logs
# ==============================================================================
def test_scenario_15_secrets_absent_from_logs(tmp_path):
    secret_key = "sec_super_secret_agenticorg_key_998877"
    log_file = tmp_path / "test_audit.log"

    settings = Settings(
        agenticorg_api_key=secret_key,
        audit_log_file=str(log_file),
        redact_sensitive_data=True,
    )
    audit_logger = AuditLogger(log_file=str(log_file), redact_sensitive=True)
    service = AgenticOrgDiscoveryService(settings=settings, audit_logger=audit_logger)

    # Simulate an error containing the secret key
    error_with_secret = f"Failed to connect to server with key: {secret_key}"
    mock_client = MockAgenticOrgClient(connectors_data=Exception(error_with_secret))
    service.discover_tenant(client=mock_client)

    # Read log file and in-memory entries
    log_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert secret_key not in log_content

    for entry in audit_logger.get_all_entries():
        assert secret_key not in entry.details
        assert secret_key not in str(entry.metadata)


# ==============================================================================
# Test 16: CLI status command works without credentials
# ==============================================================================
def test_scenario_16_cli_status_works_without_credentials(monkeypatch):
    monkeypatch.setenv("AGENTICORG_API_KEY", "")
    monkeypatch.setenv("AGENTICORG_GRANTEX_TOKEN", "")

    captured_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_out)

    # Run CLI status handler
    handle_agenticorg_status()

    output = captured_out.getvalue()
    assert "Aarogya — AgenticOrg Fleet Authentication & Tenant Status" in output
    assert "Credentials Configured: No" in output
    assert "NOT_CONFIGURED" in output
    assert "Simulation Mode" in output
