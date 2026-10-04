"""Module 8 Tests: Connector & MCP Capability Synchronization Engine.

Validates normalization, domain classification, independent state preservation,
safe reconciliation, failure handling, operational policy evaluation,
audit sanitization, zero operational execution, and CLI diagnostics.
"""

import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from aarogya.config import Settings
from aarogya.models.enums import (
    HealthcareDomain,
    CapabilityPolicyDecision,
    DiscoveryStatus,
    AuditEventType,
    ExecutionMode,
)
from aarogya.models.connector import (
    NormalizedCapability,
    SyncHistoryRecord,
    CapabilityPolicyEvaluation,
)
from aarogya.connectors.capability_synchronizer import (
    CapabilitySynchronizer,
    classify_capability,
    DIRECT_PHARMACY_OPERATIONS,
)
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.orchestrator.audit_logger import AuditLogger
from aarogya.cli import handle_capabilities, handle_capability_sync


@pytest.fixture
def clean_synchronizer(tmp_path):
    """Provide an isolated CapabilitySynchronizer instance with temporary audit log."""
    log_file = tmp_path / "test_audit.jsonl"
    settings = Settings(
        execution_mode=ExecutionMode.SIMULATION,
        audit_log_file=str(log_file),
        redact_sensitive_data=True,
    )
    audit_logger = AuditLogger(log_file=str(log_file), redact_sensitive=True)
    return CapabilitySynchronizer(settings=settings, audit_logger=audit_logger)


# ------------------------------------------------------------------------------
# 1. Connector Normalization
# ------------------------------------------------------------------------------
def test_1_connector_normalization(clean_synchronizer):
    raw_connector = {
        "id": "apollo_pharmacy",
        "name": "Apollo Direct Pharmacy API",
        "description": "Apollo Direct Pharmacy partner integration for medicine stock",
        "provider": "Apollo Pharmacy Network",
        "category": "pharmacy",
        "capabilities": ["check_inventory", "get_product_details", "reserve_stock"],
        "status": "active",
        "authorized": True,
        "healthy": True,
        "version": "1.4.0",
        "api_key": "secret_key_12345",  # Sensitive field
    }

    norm = clean_synchronizer.normalize_connector(raw_connector)

    assert norm.capability_id == "conn:apollo_pharmacy"
    assert norm.tenant_connector_id == "apollo_pharmacy"
    assert norm.mcp_tool_id is None
    assert norm.source_platform == "agenticorg"
    assert norm.display_name == "Apollo Direct Pharmacy API"
    assert norm.domain == HealthcareDomain.MEDICINE_AVAILABILITY
    assert norm.is_verified_healthcare_partner is True
    assert norm.registered is True
    assert norm.connected is True
    assert norm.healthy is True
    assert norm.authorized is True
    assert norm.capable is True
    assert norm.is_stale is False
    assert "check_inventory" in norm.supported_operations
    # Sensitive field must be stripped from raw_metadata
    assert "api_key" not in norm.raw_metadata


# ------------------------------------------------------------------------------
# 2. MCP Tool Normalization
# ------------------------------------------------------------------------------
def test_2_mcp_tool_normalization(clean_synchronizer):
    raw_tool = {
        "name": "create_caregiver_task",
        "description": "Create a new pending caregiving task for family members",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    }

    norm = clean_synchronizer.normalize_mcp_tool(raw_tool)

    assert norm.capability_id == "mcp:create_caregiver_task"
    assert norm.mcp_tool_id == "create_caregiver_task"
    assert norm.tenant_connector_id is None
    assert norm.category == "mcp_tool"
    assert norm.domain == HealthcareDomain.CAREGIVER_TASKS
    assert norm.registered is True
    assert norm.connected is True
    assert norm.authorized is None  # Unknown: MCP tool discovery does NOT imply tenant RBAC authorization
    assert norm.healthy is None     # Unknown: Not pinged or health-checked
    assert norm.capable is True
    assert norm.is_stale is False
    assert norm.supported_operations == ["create_caregiver_task"]


# ------------------------------------------------------------------------------
# 3. Missing Metadata Handling
# ------------------------------------------------------------------------------
def test_3_missing_metadata_handled_gracefully(clean_synchronizer):
    minimal_connector = {"id": "minimal_service"}
    norm_conn = clean_synchronizer.normalize_connector(minimal_connector)

    assert norm_conn.capability_id == "conn:minimal_service"
    assert norm_conn.description == ""
    assert norm_conn.input_schema is None
    assert norm_conn.output_schema is None
    assert norm_conn.source_metadata_version is None
    assert norm_conn.connected is None
    assert norm_conn.healthy is None
    assert norm_conn.authorized is None
    assert norm_conn.domain == HealthcareDomain.UNKNOWN

    minimal_mcp = {}
    norm_mcp = clean_synchronizer.normalize_mcp_tool(minimal_mcp)
    assert norm_mcp.capability_id == "mcp:unnamed_mcp_tool"
    assert norm_mcp.input_schema is None
    assert norm_mcp.output_schema is None


# ------------------------------------------------------------------------------
# 4. Unknown Tool Classification
# ------------------------------------------------------------------------------
def test_4_unknown_tool_classification(clean_synchronizer):
    raw_tool = {
        "name": "crypto_arbitrage_trading_engine",
        "description": "Executes automated multi-exchange crypto token trades",
    }
    norm = clean_synchronizer.normalize_mcp_tool(raw_tool)

    assert norm.domain == HealthcareDomain.UNKNOWN
    assert norm.is_verified_healthcare_partner is False


# ------------------------------------------------------------------------------
# 5. Duplicate Tool IDs Deduplication
# ------------------------------------------------------------------------------
def test_5_duplicate_tool_ids_deduplicated(clean_synchronizer):
    dup1 = clean_synchronizer.normalize_mcp_tool({
        "name": "duplicate_check_tool",
        "description": "First instance",
    })
    dup2 = clean_synchronizer.normalize_mcp_tool({
        "name": "duplicate_check_tool",
        "description": "Second instance with updated desc",
    })

    added, updated, stale = clean_synchronizer.reconcile_capabilities([dup1, dup2])

    assert len(clean_synchronizer.capabilities) == 1
    assert "mcp:duplicate_check_tool" in clean_synchronizer.capabilities
    # The last occurrence wins during incoming batch deduplication
    assert clean_synchronizer.capabilities["mcp:duplicate_check_tool"].description == "Second instance with updated desc"


# ------------------------------------------------------------------------------
# 6. New Capability Registration (Not Automatically Authorized)
# ------------------------------------------------------------------------------
def test_6_new_capability_registration_not_auto_authorized(clean_synchronizer):
    raw_connector = {
        "id": "unverified_partner_gateway",
        "name": "Partner Gateway",
        "description": "External partner gateway",
        "status": "active",
    }
    norm = clean_synchronizer.normalize_connector(raw_connector)
    added, updated, stale = clean_synchronizer.reconcile_capabilities([norm])

    assert "conn:unverified_partner_gateway" in added
    registered_cap = clean_synchronizer.capabilities["conn:unverified_partner_gateway"]
    assert registered_cap.registered is True
    # Crucial security rule: New capability must NOT be automatically authorized!
    assert registered_cap.authorized is not True


# ------------------------------------------------------------------------------
# 7. Existing Capability Metadata Update
# ------------------------------------------------------------------------------
def test_7_existing_capability_metadata_update(clean_synchronizer):
    initial = clean_synchronizer.normalize_connector({
        "id": "medplus_pharmacy",
        "name": "MedPlus Pharmacy",
        "description": "Initial description",
        "capabilities": ["check_inventory"],
    })
    clean_synchronizer.reconcile_capabilities([initial])

    # Re-discover with updated operations and description
    updated_input = clean_synchronizer.normalize_connector({
        "id": "medplus_pharmacy",
        "name": "MedPlus Direct Pharmacy API v2",
        "description": "Updated direct integration description",
        "capabilities": ["check_inventory", "get_price", "reserve_stock"],
    })
    added, updated, stale = clean_synchronizer.reconcile_capabilities([updated_input])

    assert "conn:medplus_pharmacy" in updated
    cap = clean_synchronizer.capabilities["conn:medplus_pharmacy"]
    assert cap.display_name == "MedPlus Direct Pharmacy API v2"
    assert "reserve_stock" in cap.supported_operations


# ------------------------------------------------------------------------------
# 8. Local Authorization Preservation
# ------------------------------------------------------------------------------
def test_8_local_authorization_preserved_on_update(clean_synchronizer):
    initial = clean_synchronizer.normalize_connector({
        "id": "secure_task_engine",
        "name": "Caregiver Task Engine",
        "authorized": True,  # Locally managed / granted authorization
    })
    clean_synchronizer.reconcile_capabilities([initial])
    assert clean_synchronizer.capabilities["conn:secure_task_engine"].authorized is True

    # Incoming discovery lacks authorization information (None)
    incoming = clean_synchronizer.normalize_connector({
        "id": "secure_task_engine",
        "name": "Caregiver Task Engine",
        "description": "Refreshed metadata",
    })
    assert incoming.authorized is None

    clean_synchronizer.reconcile_capabilities([incoming])
    # Local authorization must NOT be wiped out by an unverified discovery response
    assert clean_synchronizer.capabilities["conn:secure_task_engine"].authorized is True


# ------------------------------------------------------------------------------
# 9. Removed Capability Marked Stale (Not Deleted)
# ------------------------------------------------------------------------------
def test_9_removed_capability_marked_stale_not_deleted(clean_synchronizer):
    cap1 = clean_synchronizer.normalize_connector({"id": "conn_alpha", "name": "Alpha Service"})
    cap2 = clean_synchronizer.normalize_connector({"id": "conn_beta", "name": "Beta Service"})
    clean_synchronizer.reconcile_capabilities([cap1, cap2])

    assert len(clean_synchronizer.capabilities) == 2

    # Second sync: conn_beta is removed from tenant discovery
    added, updated, stale = clean_synchronizer.reconcile_capabilities([cap1])

    assert "conn:conn_beta" in stale
    # Must NOT be deleted from registry
    assert "conn:conn_beta" in clean_synchronizer.capabilities
    assert clean_synchronizer.capabilities["conn:conn_beta"].is_stale is True
    assert clean_synchronizer.capabilities["conn:conn_alpha"].is_stale is False


# ------------------------------------------------------------------------------
# 10. Failed Discovery Preserves Previous Known State
# ------------------------------------------------------------------------------
def test_10_failed_discovery_preserves_previous_state(clean_synchronizer):
    cap1 = clean_synchronizer.normalize_connector({"id": "essential_gateway", "name": "Essential Gateway"})
    clean_synchronizer.reconcile_capabilities([cap1])
    assert len(clean_synchronizer.capabilities) == 1

    # Simulate discovery failure response
    failed_report = {
        "discovery_status": "failed",
        "errors": ["Tenant gateway timeout", "503 Service Unavailable"],
        "connectors": [],
        "mcp_tools": [],
    }

    sync_record = clean_synchronizer.synchronize(discovery_report=failed_report)

    assert sync_record.status == DiscoveryStatus.FAILED
    assert len(sync_record.sanitized_errors) == 2
    # The registry must NOT be overwritten with an empty catalog!
    assert len(clean_synchronizer.capabilities) == 1
    assert "conn:essential_gateway" in clean_synchronizer.capabilities
    assert clean_synchronizer.capabilities["conn:essential_gateway"].is_stale is False


# ------------------------------------------------------------------------------
# 11. Partial Connector/MCP Synchronization
# ------------------------------------------------------------------------------
def test_11_partial_discovery_synchronization(clean_synchronizer):
    conn = clean_synchronizer.normalize_connector({"id": "my_conn", "name": "My Connector"})
    mcp = clean_synchronizer.normalize_mcp_tool({"name": "my_tool", "description": "My Tool"})
    clean_synchronizer.reconcile_capabilities([conn, mcp])

    # Partial report: connectors succeeded, but MCP failed
    partial_report = {
        "discovery_status": "partial",
        "errors": ["MCP tool enumeration failed: Connection reset"],
        "connectors": [{"id": "my_conn", "name": "My Connector Updated"}],
        "mcp_tools": [],
    }

    record = clean_synchronizer.synchronize(discovery_report=partial_report)

    assert record.status == DiscoveryStatus.PARTIAL
    # Connector was updated
    assert "conn:my_conn" in record.updated_capabilities
    # MCP tool was NOT falsely marked stale because MCP discovery category failed
    assert "mcp:my_tool" not in record.stale_capabilities
    assert clean_synchronizer.capabilities["mcp:my_tool"].is_stale is False


# ------------------------------------------------------------------------------
# 12. Unknown Authorization Blocks Execution Eligibility
# ------------------------------------------------------------------------------
def test_12_unknown_authorization_blocks_execution(clean_synchronizer):
    cap = clean_synchronizer.normalize_connector({
        "id": "apollo_pharmacy",
        "name": "Apollo Pharmacy Direct",
        "provider": "Apollo Pharmacy Network",
        "capabilities": ["check_inventory"],
        "status": "active",
        "authorized": None,  # Unknown authorization
        "healthy": True,
    })

    eval_result = clean_synchronizer.evaluate_capability_for_workflow(
        capability=cap,
        workflow="medicine_availability",
        required_operation="check_inventory",
    )

    assert eval_result.decision == CapabilityPolicyDecision.BLOCKED_UNAUTHORIZED
    assert "Explicit tenant authorization required" in eval_result.reason


# ------------------------------------------------------------------------------
# 13. Unhealthy Connector Blocks Eligibility
# ------------------------------------------------------------------------------
def test_13_unhealthy_connector_blocks_eligibility(clean_synchronizer):
    cap = clean_synchronizer.normalize_connector({
        "id": "apollo_pharmacy",
        "name": "Apollo Pharmacy Direct",
        "provider": "Apollo Pharmacy Network",
        "capabilities": ["check_inventory"],
        "status": "active",
        "authorized": True,
        "healthy": False,  # Unhealthy
    })

    eval_result = clean_synchronizer.evaluate_capability_for_workflow(
        capability=cap,
        workflow="medicine_availability",
        required_operation="check_inventory",
    )

    assert eval_result.decision == CapabilityPolicyDecision.BLOCKED_UNHEALTHY
    assert "Valid health check required" in eval_result.reason


# ------------------------------------------------------------------------------
# 14. Unsupported Operation Blocks Eligibility
# ------------------------------------------------------------------------------
def test_14_unsupported_operation_blocks_eligibility(clean_synchronizer):
    cap = clean_synchronizer.normalize_connector({
        "id": "apollo_pharmacy",
        "name": "Apollo Pharmacy Direct",
        "provider": "Apollo Pharmacy Network",
        "capabilities": ["check_inventory"],
        "status": "active",
        "authorized": True,
        "healthy": True,
    })

    eval_result = clean_synchronizer.evaluate_capability_for_workflow(
        capability=cap,
        workflow="medicine_availability",
        required_operation="create_order",  # Not supported
    )

    assert eval_result.decision == CapabilityPolicyDecision.BLOCKED_UNSUPPORTED_OPERATION
    assert "does not support required operation 'create_order'" in eval_result.reason


# ------------------------------------------------------------------------------
# 15. Generic Commerce Tool Is Not Treated As A Verified Pharmacy
# ------------------------------------------------------------------------------
def test_15_generic_commerce_tool_rejected_for_pharmacy_workflow(clean_synchronizer):
    raw_shopify = {
        "id": "shopify_store",
        "name": "Shopify General Storefront",
        "description": "E-commerce storefront connector for generic consumer retail",
        "category": "generic_retail",
        "capabilities": ["check_inventory", "create_order"],
        "status": "active",
        "authorized": True,
        "healthy": True,
    }
    cap = clean_synchronizer.normalize_connector(raw_shopify)

    # Must NOT be classified as verified healthcare partner
    assert cap.is_verified_healthcare_partner is False

    eval_result = clean_synchronizer.evaluate_capability_for_workflow(
        capability=cap,
        workflow="medicine_availability",
        required_operation="check_inventory",
    )

    # Must be strictly blocked from pharmacy workflow
    assert eval_result.decision == CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY
    assert "Direct Pharmacy API alignment" in eval_result.reason or "does not match workflow" in eval_result.reason


# ------------------------------------------------------------------------------
# 16. No MCP Tool Execution Occurs During Synchronization
# ------------------------------------------------------------------------------
def test_16_zero_mcp_tool_execution_during_synchronization(clean_synchronizer):
    mock_client = MagicMock()
    mock_client.mcp.tools.return_value = [
        {"name": "create_caregiver_task", "description": "Create task"},
        {"name": "dispense_medication", "description": "Dispense meds"},
    ]
    mock_client.connectors.list.return_value = []

    # Mock any operational execution methods
    mock_client.mcp.call_tool = MagicMock()
    mock_client.agents.run = MagicMock()

    from aarogya.connectors.agenticorg_discovery import AgenticOrgDiscoveryService
    discovery_svc = AgenticOrgDiscoveryService(
        settings=clean_synchronizer.settings,
        audit_logger=clean_synchronizer.audit_logger,
    )
    discovery_svc.initialize_client(custom_client=mock_client)

    report = discovery_svc.discover_tenant(mock_client)
    record = clean_synchronizer.synchronize(discovery_report=report)

    assert record.status == DiscoveryStatus.SUCCESS
    # Ensure zero operational tool execution calls occurred!
    mock_client.mcp.call_tool.assert_not_called()
    mock_client.agents.run.assert_not_called()


# ------------------------------------------------------------------------------
# 17. No Family Health Brain Mutation
# ------------------------------------------------------------------------------
def test_17_no_family_health_brain_mutation(clean_synchronizer, tmp_path):
    brain = FamilyHealthBrain()
    initial_patient_count = len(brain._patients)
    initial_timeline_count = len(brain._timeline_events)
    rajesh_before = brain.get_patient("pat_rajesh_01").model_dump_json()

    # Run discovery report with simulated capabilities
    report = {
        "discovery_status": "success",
        "connectors": [
            {
                "id": "apollo_pharmacy",
                "name": "Apollo Direct Pharmacy API",
                "capabilities": ["check_inventory"],
                "status": "active",
                "authorized": True,
                "healthy": True,
            }
        ],
        "mcp_tools": [
            {"name": "create_caregiver_task", "description": "Create task"}
        ],
    }

    clean_synchronizer.synchronize(discovery_report=report)

    # Health Brain must remain completely untouched
    assert len(brain._patients) == initial_patient_count
    assert len(brain._timeline_events) == initial_timeline_count
    rajesh_after = brain.get_patient("pat_rajesh_01").model_dump_json()
    assert rajesh_before == rajesh_after



# ------------------------------------------------------------------------------
# 18. Audit Metadata Is Sanitized
# ------------------------------------------------------------------------------
def test_18_audit_metadata_is_sanitized(clean_synchronizer, tmp_path):
    sensitive_report = {
        "discovery_status": "success",
        "connectors": [
            {
                "id": "apollo_api",
                "name": "Apollo API",
                "api_key": "top_secret_api_key_99999",
                "grantex_token": "bearer_secret_grantex_token_88888",
            }
        ],
        "mcp_tools": [],
        "errors": ["Failed with authorization token: secret_bearer_token"],
    }

    clean_synchronizer.synchronize(discovery_report=sensitive_report)

    # Read audit log file
    log_file = clean_synchronizer.settings.audit_log_file
    assert os.path.exists(log_file)
    with open(log_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "top_secret_api_key_99999" not in log_content
    assert "bearer_secret_grantex_token_88888" not in log_content


# ------------------------------------------------------------------------------
# 19. CLI Works Without Credentials
# ------------------------------------------------------------------------------
def test_19_cli_works_without_credentials(capsys):
    # Ensure env vars are cleared
    with patch.dict(os.environ, {"AGENTICORG_API_KEY": "", "AGENTICORG_GRANTEX_TOKEN": ""}):
        # Test capabilities display
        handle_capabilities()
        cap_output = capsys.readouterr().out
        assert "Aarogya -- Normalized Capability & MCP Tool Registry" in cap_output
        assert "CAPABILITY ID" in cap_output

        # Test capability-sync without credentials (must not fabricate live results)
        handle_capability_sync(simulated=False)
        sync_output = capsys.readouterr().out
        assert "AgenticOrg credentials not configured" in sync_output
        assert "Live tenant synchronization is unavailable" in sync_output

        # Test capability-sync with simulated fixture
        handle_capability_sync(simulated=True)
        sim_output = capsys.readouterr().out
        assert "[SIMULATED FIXTURE RUN]" in sim_output
        assert "Synchronization Summary:" in sim_output


# ------------------------------------------------------------------------------
# 20. ConnectorRegistry Integration & Policy Evaluation
# ------------------------------------------------------------------------------
def test_20_connector_registry_integration(clean_synchronizer):
    registry = ConnectorRegistry(
        execution_mode=ExecutionMode.AUTHORIZED_EXECUTION,
        synchronizer=clean_synchronizer,
    )

    report = {
        "discovery_status": "success",
        "connectors": [
            {
                "id": "apollo_pharmacy",
                "name": "Apollo Direct Pharmacy API",
                "provider": "Apollo Pharmacy Partner Network",
                "capabilities": ["check_inventory", "reserve_stock"],
                "status": "active",
                "authorized": True,
                "healthy": True,
            }
        ],
        "mcp_tools": [],
    }

    record = registry.sync_capabilities(discovery_report=report)
    assert record.status == DiscoveryStatus.SUCCESS
    assert len(registry.list_normalized_capabilities()) == 1

    # Policy evaluation for eligible operation
    eval_eligible = registry.evaluate_capability_policy(
        capability_id="conn:apollo_pharmacy",
        workflow="medicine_availability",
        required_operation="check_inventory",
    )
    assert eval_eligible.decision == CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW
    assert "Eligible for policy review only" in eval_eligible.reason

    # Policy evaluation for unregistered capability
    eval_unreg = registry.evaluate_capability_policy(
        capability_id="conn:non_existent",
        workflow="medicine_availability",
        required_operation="check_inventory",
    )
    assert eval_unreg.decision == CapabilityPolicyDecision.BLOCKED_NOT_REGISTERED
