"""Module 10 Test Suite: Durable Registry, Execution State & Audit Persistence.

Validates that connector capabilities, synchronization history, execution records,
idempotency keys, approval references, and structured audit events survive process
restarts, while preserving strict healthcare authorization, HITL approvals,
concurrency safety, and zero live execution boundaries.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta
import pytest

from aarogya.config import Settings, ExecutionMode
from aarogya.models.enums import (
    HealthcareDomain,
    GatewayExecutionStatus,
    CapabilityPolicyDecision,
    ApprovalStatus,
    ActionType,
    AuditEventType,
    DiscoveryStatus,
    VerificationStatus,
)
from aarogya.models.connector import NormalizedCapability, SyncHistoryRecord
from aarogya.models.approval import ApprovalRecord, compute_parameter_hash
from aarogya.models.gateway import ExecutionRequest, ExecutionResult
from aarogya.models.audit import AuditLogEntry
from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.persistence import (
    SQLiteStore,
    CURRENT_SCHEMA_VERSION,
    get_persistence_bundle,
    SQLiteCapabilityRepository,
    SQLiteSyncHistoryRepository,
    SQLiteExecutionRepository,
    SQLiteIdempotencyRepository,
    SQLiteApprovalRepository,
    SQLiteAuditRepository,
)
from aarogya.connectors.capability_synchronizer import CapabilitySynchronizer
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.workflows.approval_manager import ApprovalManager
from aarogya.orchestrator.audit_logger import AuditLogger
from aarogya.orchestrator.execution_gateway import ExecutionGateway


@pytest.fixture
def temp_db_path(tmp_path):
    """Provides a fresh temporary database file path for isolated persistence tests."""
    db_file = tmp_path / f"test_aarogya_{uuid.uuid4().hex[:8]}.db"
    return str(db_file)


# ------------------------------------------------------------------------------
# 1. Database Initialization
# ------------------------------------------------------------------------------
def test_01_database_initialization(temp_db_path):
    """Test that SQLiteStore initializes all required tables and safety pragmas."""
    store = SQLiteStore(temp_db_path, auto_init=True)
    try:
        tables = store.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {t["name"] for t in tables}
        expected = {
            "schema_version",
            "capabilities",
            "sync_history",
            "execution_records",
            "idempotency_records",
            "approvals",
            "audit_events",
        }
        assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"

        # Verify foreign keys are enabled
        fk = store.fetchone("PRAGMA foreign_keys")
        assert fk["foreign_keys"] == 1
    finally:
        store.close()


# ------------------------------------------------------------------------------
# 2. Schema Version Initialization
# ------------------------------------------------------------------------------
def test_02_schema_version_initialization(temp_db_path):
    """Test that schema migrations track version 1 and migrations are idempotent."""
    store = SQLiteStore(temp_db_path, auto_init=True)
    try:
        ver_row = store.fetchone("SELECT MAX(version) AS ver FROM schema_version")
        assert ver_row is not None
        assert ver_row["ver"] == CURRENT_SCHEMA_VERSION

        # Re-running initialization must be safely idempotent
        store.initialize()
        ver_row2 = store.fetchone("SELECT MAX(version) AS ver FROM schema_version")
        assert ver_row2["ver"] == CURRENT_SCHEMA_VERSION
    finally:
        store.close()


# ------------------------------------------------------------------------------
# 3. Capability Persistence
# ------------------------------------------------------------------------------
def test_03_capability_persistence(temp_db_path):
    """Test saving and retrieving a normalized capability with all independent readiness axes."""
    store = SQLiteStore(temp_db_path)
    repo = SQLiteCapabilityRepository(store)
    try:
        cap = NormalizedCapability(
            capability_id="conn:apollo_pharmacy",
            source_platform="agenticorg",
            tenant_connector_id="apollo_01",
            display_name="Apollo Pharmacy Partner",
            description="Direct inventory and orders",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            category="pharmacy",
            supported_operations=["check_inventory", "create_order"],
            documented=True,
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            is_stale=False,
            raw_metadata={"rate_limit": 100},
        )
        repo.save(cap)
        assert repo.count() == 1

        retrieved = repo.get("conn:apollo_pharmacy")
        assert retrieved is not None
        assert retrieved.capability_id == "conn:apollo_pharmacy"
        assert retrieved.display_name == "Apollo Pharmacy Partner"
        assert retrieved.domain == HealthcareDomain.MEDICINE_AVAILABILITY
        assert retrieved.authorized is True
        assert retrieved.healthy is True
        assert retrieved.is_verified_healthcare_partner is True
        assert "create_order" in retrieved.supported_operations
        assert retrieved.raw_metadata.get("rate_limit") == 100
    finally:
        store.close()


# ------------------------------------------------------------------------------
# 4. Capability Retrieval After Repository Recreation
# ------------------------------------------------------------------------------
def test_04_capability_retrieval_after_repository_recreation(temp_db_path):
    """Test that capabilities survive complete application/store restart."""
    store1 = SQLiteStore(temp_db_path)
    repo1 = SQLiteCapabilityRepository(store1)
    cap = NormalizedCapability(
        capability_id="conn:task_manager",
        source_platform="agenticorg",
        display_name="Family Task Backend",
        domain=HealthcareDomain.CAREGIVER_TASKS,
        supported_operations=["create_caregiver_task"],
        documented=True,
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=True,
    )
    repo1.save(cap)
    store1.close()

    # Recreate completely new store and repository pointing to the same file
    store2 = SQLiteStore(temp_db_path)
    repo2 = SQLiteCapabilityRepository(store2)
    try:
        retrieved = repo2.get("conn:task_manager")
        assert retrieved is not None
        assert retrieved.capability_id == "conn:task_manager"
        assert retrieved.display_name == "Family Task Backend"
        assert retrieved.authorized is True
        assert retrieved.healthy is True
    finally:
        store2.close()


# ------------------------------------------------------------------------------
# 5. Authorization Preservation Across Synchronization
# ------------------------------------------------------------------------------
def test_05_authorization_preservation_across_synchronization(temp_db_path):
    """Test that locally granted authorization is strictly preserved when metadata is updated."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        # 1. Establish capability with explicit local authorization
        cap = NormalizedCapability(
            capability_id="conn:apollo_pharmacy",
            source_platform="agenticorg",
            display_name="Apollo Direct",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            documented=True,
            registered=True,
            authorized=True,  # Local authorization granted
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
        )
        bundle.capability_repo.save(cap)

        # 2. Simulate discovery refresh where remote metadata has authorized=None or False
        synchronizer = CapabilitySynchronizer(
            settings=Settings(),
            capability_repo=bundle.capability_repo,
            sync_history_repo=bundle.sync_history_repo,
        )
        incoming = NormalizedCapability(
            capability_id="conn:apollo_pharmacy",
            source_platform="agenticorg",
            display_name="Apollo Direct (Updated Metadata)",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory", "get_price"],
            documented=True,
            registered=True,
            authorized=None,  # Unknown from remote tenant discovery
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
        )
        added, updated, stale = synchronizer.reconcile_capabilities([incoming])
        assert "conn:apollo_pharmacy" in updated

        # 3. Verify in repository that authorized remains True
        stored = bundle.capability_repo.get("conn:apollo_pharmacy")
        assert stored.authorized is True
        assert stored.display_name == "Apollo Direct (Updated Metadata)"
        assert "get_price" in stored.supported_operations
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 6. Stale Capability Persistence
# ------------------------------------------------------------------------------
def test_06_stale_capability_persistence(temp_db_path):
    """Test that stale capabilities are preserved with is_stale=True rather than deleted."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        cap = NormalizedCapability(
            capability_id="conn:old_provider",
            source_platform="agenticorg",
            display_name="Decommissioned Provider",
            domain=HealthcareDomain.UNKNOWN,
            supported_operations=["legacy_op"],
            is_stale=False,
        )
        bundle.capability_repo.save(cap)
        bundle.capability_repo.mark_stale("conn:old_provider")

        retrieved = bundle.capability_repo.get("conn:old_provider")
        assert retrieved is not None
        assert retrieved.is_stale is True

        # Listing non-stale excludes it, include_stale includes it
        active_list = bundle.capability_repo.list_all(include_stale=False)
        assert len(active_list) == 0
        all_list = bundle.capability_repo.list_all(include_stale=True)
        assert len(all_list) == 1
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 7. Failed Discovery Does Not Erase Catalog
# ------------------------------------------------------------------------------
def test_07_failed_discovery_does_not_erase_catalog(temp_db_path):
    """Test that failed discovery leaves existing database catalog completely untouched."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        cap = NormalizedCapability(
            capability_id="conn:safe_connector",
            source_platform="agenticorg",
            display_name="Safe Connector",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
        )
        bundle.capability_repo.save(cap)

        synchronizer = CapabilitySynchronizer(
            settings=Settings(),
            capability_repo=bundle.capability_repo,
            sync_history_repo=bundle.sync_history_repo,
        )
        failed_report = {
            "discovery_status": DiscoveryStatus.FAILED.value,
            "errors": ["Connection timed out to AgenticOrg fleet"],
        }
        res = synchronizer.synchronize(discovery_report=failed_report)
        assert res.status == DiscoveryStatus.FAILED

        # Verify catalog unchanged
        assert bundle.capability_repo.count() == 1
        stored = bundle.capability_repo.get("conn:safe_connector")
        assert stored.is_stale is False
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 8. Partial Discovery Preserves Unrelated Categories
# ------------------------------------------------------------------------------
def test_08_partial_discovery_preserves_unrelated_capability_categories(temp_db_path):
    """Test that partial discovery updating connectors does not mark MCP tools as stale."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        conn_cap = NormalizedCapability(
            capability_id="conn:apollo_pharma",
            source_platform="agenticorg",
            display_name="Apollo Pharma",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
        )
        mcp_cap = NormalizedCapability(
            capability_id="mcp:vital_signs_tracker",
            source_platform="agenticorg",
            display_name="Vital Signs Tracker",
            domain=HealthcareDomain.CAREGIVER_TASKS,
            supported_operations=["log_vitals"],
        )
        bundle.capability_repo.save_all([conn_cap, mcp_cap])

        synchronizer = CapabilitySynchronizer(
            settings=Settings(),
            capability_repo=bundle.capability_repo,
            sync_history_repo=bundle.sync_history_repo,
        )
        # Partial report where only connectors succeeded (mcp failed)
        partial_report = {
            "discovery_status": DiscoveryStatus.PARTIAL.value,
            "connectors": [{"id": "apollo_pharma", "name": "Apollo Pharma", "capabilities": ["check_inventory"]}],
            "mcp_tools": [],
            "errors": ["MCP server timeout"],
        }
        res = synchronizer.synchronize(discovery_report=partial_report)
        assert res.status == DiscoveryStatus.PARTIAL

        # MCP tool must NOT be marked stale
        mcp_stored = bundle.capability_repo.get("mcp:vital_signs_tracker")
        assert mcp_stored.is_stale is False
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 9. Synchronization History Survives Restart
# ------------------------------------------------------------------------------
def test_09_synchronization_history_survives_restart(temp_db_path):
    """Test that sync history records persist and can be read after store re-creation."""
    store1 = SQLiteStore(temp_db_path)
    sync_repo1 = SQLiteSyncHistoryRepository(store1)
    rec = SyncHistoryRecord(
        sync_id="sync_test_001",
        started_at=datetime.utcnow() - timedelta(seconds=5),
        completed_at=datetime.utcnow(),
        discovery_source="agenticorg_tenant",
        added_capabilities=["conn:apollo_pharmacy"],
        updated_capabilities=["conn:task_manager"],
        stale_capabilities=[],
        status=DiscoveryStatus.SUCCESS,
    )
    sync_repo1.record_sync(rec)
    store1.close()

    store2 = SQLiteStore(temp_db_path)
    sync_repo2 = SQLiteSyncHistoryRepository(store2)
    try:
        latest = sync_repo2.get_latest_sync()
        assert latest is not None
        assert latest.sync_id == "sync_test_001"
        assert latest.status == DiscoveryStatus.SUCCESS
        assert "conn:apollo_pharmacy" in latest.added_capabilities
    finally:
        store2.close()


# ------------------------------------------------------------------------------
# 10. Execution Record Persistence
# ------------------------------------------------------------------------------
def test_10_execution_record_persistence(temp_db_path):
    """Test persisting and querying gateway execution results."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        res = ExecutionResult(
            execution_id="exec_test_001",
            request_id="req_001",
            capability_id="conn:apollo_pharmacy",
            operation="check_inventory",
            status=GatewayExecutionStatus.SIMULATED,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
            handler_invoked=True,
            is_simulated=True,
            output={"stock": 50, "medicine": "Metformin"},
            verification_status=VerificationStatus.NOT_APPLICABLE,
        )
        bundle.execution_repo.save_execution(res)

        fetched = bundle.execution_repo.get_execution("exec_test_001")
        assert fetched is not None
        assert fetched.execution_id == "exec_test_001"
        assert fetched.status == GatewayExecutionStatus.SIMULATED
        assert fetched.output.get("stock") == 50

        by_req = bundle.execution_repo.get_by_request_id("req_001")
        assert by_req is not None
        assert by_req.execution_id == "exec_test_001"
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 11. Execution Status Transition Validation
# ------------------------------------------------------------------------------
def test_11_execution_status_transition_validation(temp_db_path):
    """Test updating execution record status across lifecycle transitions."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        res = ExecutionResult(
            execution_id="exec_trans_01",
            request_id="req_trans_01",
            capability_id="conn:apollo_pharmacy",
            operation="create_order",
            status=GatewayExecutionStatus.READY,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
            handler_invoked=False,
        )
        bundle.execution_repo.save_execution(res)

        bundle.execution_repo.update_status(
            execution_id="exec_trans_01",
            status=GatewayExecutionStatus.SUCCEEDED,
            error_category=None,
        )

        updated = bundle.execution_repo.get_execution("exec_trans_01")
        assert updated.status == GatewayExecutionStatus.SUCCEEDED
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 12. Idempotency Key Uniqueness
# ------------------------------------------------------------------------------
def test_12_idempotency_key_uniqueness(temp_db_path):
    """Test that idempotency keys enforce database uniqueness constraint."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        # Create execution record for foreign key reference
        exec_res = ExecutionResult(
            execution_id="exec_unique_01",
            request_id="req_unique_01",
            capability_id="conn:apollo_pharmacy",
            operation="reserve_stock",
            status=GatewayExecutionStatus.READY,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
        )
        bundle.execution_repo.save_execution(exec_res)

        # First claim succeeds
        claim1 = bundle.idempotency_repo.claim_key(
            idempotency_key="idemp_key_abc123",
            execution_id="exec_unique_01",
            user_id="usr_amit_01",
            operation="reserve_stock",
            request_fingerprint="fingerprint_hash_1",
        )
        assert claim1 is True

        # Second claim with same key fails via database constraint
        claim2 = bundle.idempotency_repo.claim_key(
            idempotency_key="idemp_key_abc123",
            execution_id="exec_unique_01",
            user_id="usr_amit_01",
            operation="reserve_stock",
            request_fingerprint="fingerprint_hash_1",
        )
        assert claim2 is False
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 13. Duplicate Request After Gateway Recreation
# ------------------------------------------------------------------------------
def test_13_duplicate_request_after_gateway_recreation(temp_db_path):
    """Test that duplicate idempotency requests survive complete gateway reinitialization."""
    bundle1 = get_persistence_bundle(temp_db_path)
    cap = NormalizedCapability(
        capability_id="conn:apollo_pharmacy",
        source_platform="agenticorg",
        tenant_connector_id="apollo_pharmacy",
        display_name="Apollo Direct Pharmacy API",
        domain=HealthcareDomain.MEDICINE_AVAILABILITY,
        supported_operations=["check_inventory", "reserve_stock", "create_order"],
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=True,
        is_stale=False,
    )
    bundle1.capability_repo.save(cap)

    reg1 = ConnectorRegistry(capability_repo=bundle1.capability_repo)
    gw1 = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        connector_registry=reg1,
        execution_repo=bundle1.execution_repo,
        idempotency_repo=bundle1.idempotency_repo,
    )
    req = ExecutionRequest(
        request_id="req_restart_01",
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        idempotency_key="idemp_restart_key_777",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res1 = gw1.execute(req)
    assert res1.status == GatewayExecutionStatus.SIMULATED
    bundle1.store.close()

    # Recreate store and gateway from same DB
    bundle2 = get_persistence_bundle(temp_db_path)
    reg2 = ConnectorRegistry(capability_repo=bundle2.capability_repo)
    gw2 = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        connector_registry=reg2,
        execution_repo=bundle2.execution_repo,
        idempotency_repo=bundle2.idempotency_repo,
    )
    try:
        res2 = gw2.execute(req)
        assert res2.idempotency_matched is True
        assert res2.status == GatewayExecutionStatus.SIMULATED
    finally:
        bundle2.store.close()


# ------------------------------------------------------------------------------
# 14. Concurrent Idempotency Claim Protection
# ------------------------------------------------------------------------------
def test_14_concurrent_idempotency_claim_protection(temp_db_path):
    """Test that concurrent execution claims on the same key are safely rejected."""
    bundle = get_persistence_bundle(temp_db_path)
    cap = NormalizedCapability(
        capability_id="conn:apollo_pharmacy",
        source_platform="agenticorg",
        tenant_connector_id="apollo_pharmacy",
        display_name="Apollo Direct Pharmacy API",
        domain=HealthcareDomain.MEDICINE_AVAILABILITY,
        supported_operations=["check_inventory", "reserve_stock", "create_order"],
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=True,
        is_stale=False,
    )
    bundle.capability_repo.save(cap)
    reg = ConnectorRegistry(capability_repo=bundle.capability_repo)
    gw = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        connector_registry=reg,
        execution_repo=bundle.execution_repo,
        idempotency_repo=bundle.idempotency_repo,
    )
    try:
        # Pre-claim key manually to simulate a concurrent thread claiming it first
        exec_placeholder = ExecutionResult(
            execution_id="exec_concurrent_prior",
            request_id="req_concurrent_prior",
            capability_id="conn:apollo_pharmacy",
            operation="check_inventory",
            status=GatewayExecutionStatus.READY,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
        )
        bundle.execution_repo.save_execution(exec_placeholder)
        bundle.idempotency_repo.claim_key(
            idempotency_key="idemp_concurrent_key",
            execution_id="exec_concurrent_prior",
            user_id="usr_amit_01",
            operation="check_inventory",
            request_fingerprint="fp_hash",
        )

        # Incoming request attempts to claim same key
        req = ExecutionRequest(
            request_id="req_concurrent_new",
            capability_id="conn:apollo_pharmacy",
            requested_operation="check_inventory",
            input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
            requesting_user_id="usr_amit_01",
            patient_id="pat_rajesh_01",
            idempotency_key="idemp_concurrent_key",
            execution_mode=ExecutionMode.SIMULATION,
        )
        res = gw.execute(req)
        assert res.status == GatewayExecutionStatus.REJECTED
        assert res.error_category == "CONCURRENT_IDEMPOTENCY_CLAIM"
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 15. Approval Reference Persistence
# ------------------------------------------------------------------------------
def test_15_approval_reference_persistence(temp_db_path):
    """Test persisting, retrieving, and granting HITL approvals via ApprovalManager and repository."""
    bundle = get_persistence_bundle(temp_db_path)
    mgr = ApprovalManager(approval_repo=bundle.approval_repo)
    try:
        rec = mgr.request_approval(
            request_id="req_app_01",
            user_identity="usr_amit_01",
            action_type=ActionType.PLACE_MEDICINE_ORDER,
            parameters={"medicine_name": "Metformin", "quantity": 30},
        )
        assert rec.approval_status == ApprovalStatus.PENDING

        # Verify persisted
        retrieved = bundle.approval_repo.get_approval(rec.approval_id)
        assert retrieved is not None
        assert retrieved.approval_status == ApprovalStatus.PENDING
        assert retrieved.parameter_hash == rec.parameter_hash

        # Grant approval
        success, msg, granted_rec = mgr.grant_approval(
            approval_id=rec.approval_id,
            user_identity="usr_amit_01",
        )
        assert success is True
        assert granted_rec.approval_status == ApprovalStatus.GRANTED

        # Check repository updated
        updated_repo_rec = bundle.approval_repo.get_approval(rec.approval_id)
        assert updated_repo_rec.approval_status == ApprovalStatus.GRANTED
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 16. Approval Binding Remains Enforced
# ------------------------------------------------------------------------------
def test_16_approval_binding_remains_enforced(temp_db_path):
    """Test that modifying parameters invalidates a persisted approval."""
    bundle = get_persistence_bundle(temp_db_path)
    mgr = ApprovalManager(approval_repo=bundle.approval_repo)
    try:
        rec = mgr.request_approval(
            request_id="req_bind_01",
            user_identity="usr_amit_01",
            action_type=ActionType.PLACE_MEDICINE_ORDER,
            parameters={"medicine_name": "Metformin", "quantity": 30},
        )
        # Attempting grant with tampered parameters revokes approval
        success, msg, rev_rec = mgr.grant_approval(
            approval_id=rec.approval_id,
            user_identity="usr_amit_01",
            provided_parameters={"medicine_name": "Metformin", "quantity": 60},  # Tampered!
        )
        assert success is False
        assert rev_rec.approval_status == ApprovalStatus.REVOKED

        stored = bundle.approval_repo.get_approval(rec.approval_id)
        assert stored.approval_status == ApprovalStatus.REVOKED
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 17. Expired Approval Remains Invalid
# ------------------------------------------------------------------------------
def test_17_expired_approval_remains_invalid(temp_db_path):
    """Test that an expired approval cannot be granted."""
    bundle = get_persistence_bundle(temp_db_path)
    mgr = ApprovalManager(approval_repo=bundle.approval_repo)
    try:
        rec = mgr.request_approval(
            request_id="req_exp_01",
            user_identity="usr_amit_01",
            action_type=ActionType.PLACE_MEDICINE_ORDER,
            parameters={"medicine_name": "Metformin", "quantity": 30},
        )
        # Set expiration to past
        rec.expiration = datetime.utcnow() - timedelta(minutes=10)
        bundle.approval_repo.save_approval(rec)

        success, msg, exp_rec = mgr.grant_approval(
            approval_id=rec.approval_id,
            user_identity="usr_amit_01",
        )
        assert success is False
        assert "expired" in msg.lower()
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 18. Audit Event Persistence
# ------------------------------------------------------------------------------
def test_18_audit_event_persistence(temp_db_path):
    """Test recording and querying structured audit events in database."""
    bundle = get_persistence_bundle(temp_db_path)
    logger = AuditLogger(log_file=None, audit_repo=bundle.audit_repo)
    try:
        logger.log(
            event_type=AuditEventType.GATEWAY_EXECUTION_REQUESTED,
            status="received",
            details="Gateway request received for inventory check",
            request_id="req_aud_001",
            user_id="usr_amit_01",
            patient_id="pat_rajesh_01",
            metadata={"source": "unit_test"},
        )

        events = bundle.audit_repo.list_events(request_id="req_aud_001")
        assert len(events) == 1
        assert events[0].event_type == AuditEventType.GATEWAY_EXECUTION_REQUESTED
        assert events[0].details == "Gateway request received for inventory check"
        assert events[0].metadata.get("source") == "unit_test"
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 19. Secret Redaction in Persisted Records
# ------------------------------------------------------------------------------
def test_19_secret_redaction_in_persisted_records(temp_db_path):
    """Test that API secrets and keys are redacted before saving to audit table."""
    bundle = get_persistence_bundle(temp_db_path)
    logger = AuditLogger(log_file=None, redact_sensitive=True, audit_repo=bundle.audit_repo)
    try:
        logger.log(
            event_type=AuditEventType.GATEWAY_EXECUTION_BLOCKED,
            status="blocked",
            details="Testing secret redaction",
            request_id="req_secret_01",
            metadata={
                "api_key": "secret_live_token_12345",
                "grantex_token": "grantex_secret_bearer_token",
                "safe_item": "non_sensitive_data",
            },
        )
        events = bundle.audit_repo.list_events(request_id="req_secret_01")
        assert len(events) == 1
        meta = events[0].metadata
        assert meta["api_key"] == "[REDACTED]"
        assert meta["grantex_token"] == "[REDACTED]"
        assert meta["safe_item"] == "non_sensitive_data"
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 20. Interrupted Execution Recovery
# ------------------------------------------------------------------------------
def test_20_interrupted_execution_recovery(temp_db_path):
    """Test crash recovery transitions unfinalized executions to UNKNOWN_OUTCOME."""
    bundle = get_persistence_bundle(temp_db_path)
    try:
        # Simulate in-flight executions left in intermediate state before crash
        exec_crashed = ExecutionResult(
            execution_id="exec_crashed_01",
            request_id="req_crashed_01",
            capability_id="conn:apollo_pharmacy",
            operation="create_order",
            status=GatewayExecutionStatus.SUBMITTED,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
            handler_invoked=True,
        )
        bundle.execution_repo.save_execution(exec_crashed)

        # Claim idempotency
        bundle.idempotency_repo.claim_key(
            idempotency_key="idemp_crashed_key",
            execution_id="exec_crashed_01",
            user_id="usr_amit_01",
            operation="create_order",
            request_fingerprint="fp_hash",
        )

        # Run crash recovery
        recovered = bundle.execution_repo.recover_interrupted_executions()
        assert "exec_crashed_01" in recovered

        # Verify status is now UNKNOWN_OUTCOME and verification pending
        updated = bundle.execution_repo.get_execution("exec_crashed_01")
        assert updated.status == GatewayExecutionStatus.UNKNOWN_OUTCOME
        assert updated.verification_status == VerificationStatus.PENDING_VERIFICATION
        assert updated.error_category == "INTERRUPTED_EXECUTION_RECOVERED"
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 21. Uncertain Execution Is Not Automatically Retried
# ------------------------------------------------------------------------------
def test_21_uncertain_consequential_execution_is_not_automatically_retried(temp_db_path):
    """Test that retrying an execution with UNKNOWN_OUTCOME returns REQUIRES_VERIFICATION."""
    bundle = get_persistence_bundle(temp_db_path)
    gw = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        execution_repo=bundle.execution_repo,
        idempotency_repo=bundle.idempotency_repo,
    )
    try:
        # Save recovered execution in UNKNOWN_OUTCOME
        exec_res = ExecutionResult(
            execution_id="exec_uncert_01",
            request_id="req_uncert_01",
            capability_id="conn:apollo_pharmacy",
            operation="create_order",
            status=GatewayExecutionStatus.UNKNOWN_OUTCOME,
            policy_decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
            error_category="INTERRUPTED_EXECUTION_RECOVERED",
        )
        bundle.execution_repo.save_execution(exec_res)
        bundle.idempotency_repo.claim_key(
            idempotency_key="idemp_uncert_key",
            execution_id="exec_uncert_01",
            user_id="usr_amit_01",
            operation="create_order",
            request_fingerprint="fp",
        )

        req = ExecutionRequest(
            request_id="req_uncert_retry",
            capability_id="conn:apollo_pharmacy",
            requested_operation="create_order",
            input_payload={"medicine_name": "Metformin", "quantity": 30, "delivery_address": "123 Main St"},
            requesting_user_id="usr_amit_01",
            patient_id="pat_rajesh_01",
            idempotency_key="idemp_uncert_key",
            execution_mode=ExecutionMode.SIMULATION,
        )
        retry_res = gw.execute(req)
        assert retry_res.status == GatewayExecutionStatus.REQUIRES_VERIFICATION
        assert retry_res.error_category == "IDEMPOTENCY_RETRY_REQUIRES_VERIFICATION"
    finally:
        bundle.store.close()


# ------------------------------------------------------------------------------
# 22. Database Failure Blocks Unsafe Execution
# ------------------------------------------------------------------------------
def test_22_database_failure_blocks_unsafe_execution(temp_db_path):
    """Test that a database failure in idempotency claim fails safely without proceeding."""
    store = SQLiteStore(temp_db_path)
    store.close()  # Force database connection to be closed

    idemp_repo = SQLiteIdempotencyRepository(store)
    # 1. Direct repository claim with closed store must fail
    with pytest.raises(Exception):
        idemp_repo.claim_key(
            idempotency_key="idemp_broken",
            execution_id="exec_broken",
            user_id="usr_amit_01",
            operation="check_inventory",
            request_fingerprint="fp",
        )

    # 2. Gateway execution fails safely (returns BLOCKED) rather than proceeding with untracked execution
    gw = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        idempotency_repo=idemp_repo,
    )
    req = ExecutionRequest(
        request_id="req_fail_safe",
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        idempotency_key="idemp_will_fail",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gw.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.error_category == "DATABASE_FAILURE_BLOCKED"


# ------------------------------------------------------------------------------
# 23. Family Health Brain Immutability
# ------------------------------------------------------------------------------
def test_23_family_health_brain_data_is_not_modified_by_persistence(temp_db_path):
    """Test that persistence operations never mutate Family Health Brain records."""
    brain = FamilyHealthBrain()
    initial_patients = list(brain._patients.keys())
    patient = brain.get_patient("pat_rajesh_01")
    initial_prescriptions = [p.prescription_id for p in patient.prescriptions] if patient else []

    bundle = get_persistence_bundle(temp_db_path)
    cap = NormalizedCapability(
        capability_id="conn:apollo_pharmacy",
        source_platform="agenticorg",
        tenant_connector_id="apollo_pharmacy",
        display_name="Apollo Direct Pharmacy API",
        domain=HealthcareDomain.MEDICINE_AVAILABILITY,
        supported_operations=["check_inventory"],
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=True,
    )
    bundle.capability_repo.save(cap)
    reg = ConnectorRegistry(capability_repo=bundle.capability_repo)

    gw = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        brain=brain,
        connector_registry=reg,
        execution_repo=bundle.execution_repo,
        idempotency_repo=bundle.idempotency_repo,
    )
    req = ExecutionRequest(
        request_id="req_brain_safety",
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    gw.execute(req)
    bundle.store.close()

    # Assert brain records completely untouched
    final_patients = list(brain._patients.keys())
    final_patient = brain.get_patient("pat_rajesh_01")
    final_prescriptions = [p.prescription_id for p in final_patient.prescriptions] if final_patient else []
    assert initial_patients == final_patients
    assert initial_prescriptions == final_prescriptions


# ------------------------------------------------------------------------------
# 24. CLI Storage Diagnostics
# ------------------------------------------------------------------------------
def test_24_cli_storage_diagnostics(temp_db_path, monkeypatch):
    """Test that CLI diagnostic handlers run cleanly."""
    from aarogya.cli import (
        handle_storage_status,
        handle_execution_history,
        handle_sync_history,
        handle_persistence_demo,
    )
    monkeypatch.setenv("AAROGYA_DATABASE_PATH", temp_db_path)

    # All CLI diagnostic commands should run without throwing exceptions
    handle_storage_status()
    handle_execution_history(limit=5)
    handle_sync_history(limit=5)
    handle_persistence_demo(simulated=True)


# ------------------------------------------------------------------------------
# 25. JSONL Audit Import Utility
# ------------------------------------------------------------------------------
def test_25_jsonl_audit_import_utility(temp_db_path, tmp_path):
    """Test importing legacy JSONL audit entries into the SQLite database idempotently."""
    bundle = get_persistence_bundle(temp_db_path)
    jsonl_file = tmp_path / "legacy_audit.jsonl"
    entry1 = AuditLogEntry(
        audit_id="aud_import_001",
        event_type=AuditEventType.REQUEST_RECEIVED,
        status="received",
        details="Imported legacy request 1",
        execution_mode=ExecutionMode.SIMULATION,
        timestamp=datetime.utcnow(),
    )
    entry2 = AuditLogEntry(
        audit_id="aud_import_002",
        event_type=AuditEventType.PATIENT_RESOLVED,
        status="resolved",
        details="Imported legacy request 2",
        execution_mode=ExecutionMode.SIMULATION,
        timestamp=datetime.utcnow(),
    )
    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(entry1.model_dump_json() + "\n")
        f.write(entry2.model_dump_json() + "\n")

    try:
        # First import adds 2 entries
        count1 = bundle.audit_repo.import_from_jsonl(str(jsonl_file))
        assert count1 == 2

        # Second import is idempotent: duplicates ignored
        count2 = bundle.audit_repo.import_from_jsonl(str(jsonl_file))
        assert count2 == 0

        # Verify stored
        events = bundle.audit_repo.list_events()
        assert len(events) == 2
        ids = {e.audit_id for e in events}
        assert ids == {"aud_import_001", "aud_import_002"}
    finally:
        bundle.store.close()
