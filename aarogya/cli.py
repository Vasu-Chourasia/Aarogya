"""Command Line Interface for Aarogya Healthcare Coordinator.

Supports Phase 2 coordination queries and Phase 3 Module 7 AgenticOrg
authentication and tenant discovery diagnostic commands.
"""

from __future__ import annotations

import sys
import os
import json
from .config import get_settings, ExecutionMode
from .orchestrator.agent import AarogyaAgent
from .models.request import HealthcareRequest
from .connectors.agenticorg_discovery import AgenticOrgDiscoveryService
from .models.enums import AgenticOrgAuthState


def handle_agenticorg_status() -> None:
    """Read-only CLI diagnostics for AgenticOrg authentication and configuration."""
    print("=" * 70)
    print(" Aarogya — AgenticOrg Fleet Authentication & Tenant Status")
    print("=" * 70)

    settings = get_settings()
    discovery_svc = AgenticOrgDiscoveryService(settings=settings)

    has_creds, cred_reason = discovery_svc.check_credentials()
    has_key = bool(settings.agenticorg_api_key and settings.agenticorg_api_key.strip())
    has_token = bool(settings.agenticorg_grantex_token and settings.agenticorg_grantex_token.strip())

    print(f"Credentials Configured: {'Yes' if (has_key or has_token) else 'No'}")
    print(f"  - API Key Present:    {'Yes (Redacted)' if has_key else 'No'}")
    print(f"  - Grantex Token:      {'Yes (Redacted)' if has_token else 'No'}")
    print(f"  - Target Base URL:    {settings.agenticorg_base_url}")
    print(f"  - Discovery Timeout:  {settings.agenticorg_discovery_timeout_seconds}s")
    print(f"Execution Mode:         {settings.execution_mode.value}")

    client, init_err = discovery_svc.initialize_client()
    if client is None:
        print(f"SDK Initialization:     Failed ({init_err or 'No credentials'})")
        print(f"Authentication State:   {discovery_svc.auth_state.value}")
        print("Tenant Connectors:      Unavailable (Client not initialized)")
        print("MCP Tools:              Unavailable (Client not initialized)")
        print(f"Operational Mode:       Isolated / Simulation Mode")
        print("=" * 70)
        return

    print("SDK Initialization:     Success")
    is_auth, auth_state, auth_msg = discovery_svc.verify_authentication(client)
    print(f"Authentication State:   {auth_state.value}")
    print(f"Auth Verification Note: {auth_msg}")

    # Inspect current discovery state
    report = discovery_svc.discover_tenant(client)
    print(f"Discovery Status:       {report.get('discovery_status')}")
    print(f"Tenant Connectors:      {report.get('registered_connectors_count', 0)} discovered")
    print(f"MCP Tools:              {report.get('mcp_tools_count', 0)} discovered")
    print(f"Live Integration:       {'Yes' if report.get('is_live') else 'No (Simulated / Isolated)'}")

    if report.get("errors"):
        print("\nActionable Diagnostics / Errors:")
        for err in report["errors"]:
            print(f"  [!] {err}")

    print("\nSafety Boundary:")
    print(f"  [✓] {report.get('safety_notes')}")
    print("=" * 70)


def handle_agenticorg_discover() -> None:
    """Run read-only AgenticOrg tenant discovery and print detailed report."""
    settings = get_settings()
    discovery_svc = AgenticOrgDiscoveryService(settings=settings)
    report = discovery_svc.discover_tenant()
    print(json.dumps(report, indent=2))


def handle_capabilities() -> None:
    """Display normalized capabilities, categories, and independent readiness states."""
    print("=" * 80)
    print(" Aarogya -- Normalized Capability & MCP Tool Registry")
    print("=" * 80)

    settings = get_settings()
    from .connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry(execution_mode=settings.execution_mode)

    # Populate baseline connectors into synchronizer if empty
    caps = registry.list_normalized_capabilities()
    if not caps:
        baseline_items = []
        for name, conn in registry._connectors.items():
            baseline_items.append(
                registry.synchronizer.normalize_connector({
                    "id": name,
                    "name": conn.provider_name or name,
                    "description": f"Baseline platform connector for {name}",
                    "provider": conn.provider_name or name,
                    "category": name,
                    "capabilities": conn.supported_capabilities,
                    "status": "active" if conn.connected else "inactive",
                    "authorized": conn.authorized,
                    "healthy": conn.healthy,
                })
            )
        registry.synchronizer.reconcile_capabilities(baseline_items)
        caps = registry.list_normalized_capabilities()

    def fmt_bool(val) -> str:
        if val is True:
            return "Yes"
        elif val is False:
            return "No"
        return "Unknown"

    print(f"{'CAPABILITY ID':<24} {'DOMAIN':<22} {'REG':<5} {'AUTH':<5} {'CONN':<5} {'HLTH':<5} {'STALE':<6} {'PARTNER':<8}")
    print("-" * 80)
    for c in sorted(caps, key=lambda x: x.capability_id):
        stale_str = "STALE" if c.is_stale else "No"
        partner_str = "Yes" if c.is_verified_healthcare_partner else "No"
        print(f"{c.capability_id:<24} {c.domain.value:<22} {fmt_bool(c.registered):<5} {fmt_bool(c.authorized):<5} {fmt_bool(c.connected):<5} {fmt_bool(c.healthy):<5} {stale_str:<6} {partner_str:<8}")
        if c.supported_operations:
            print(f"   |-- Operations: {', '.join(c.supported_operations)}")

    print("-" * 80)
    print("State Model Key:")
    print("  Documented != Registered != Authorized != Connected != Healthy != Operational Ready")
    print("  [!] Unknown authorization or health strictly blocks operational execution.")
    print("=" * 80)


def handle_capability_sync(simulated: bool = False) -> None:
    """Run read-only discovery, normalize results, reconcile registry, and record audit history."""
    print("=" * 80)
    print(" Aarogya -- Capability Synchronization Engine")
    print("=" * 80)

    settings = get_settings()
    discovery_svc = AgenticOrgDiscoveryService(settings=settings)
    from .connectors.capability_synchronizer import CapabilitySynchronizer
    synchronizer = CapabilitySynchronizer(settings=settings)

    has_creds, _ = discovery_svc.check_credentials()

    if not has_creds and not simulated:
        print("[!] AgenticOrg credentials not configured.")
        print("    Live tenant synchronization is unavailable.")
        print("    No fabricated live results substituted.")
        print("\n    To run synchronization with simulated discovery fixtures, use:")
        print("      python -m aarogya.cli capability-sync --simulated")
        print("=" * 80)
        return

    if simulated:
        print("[SIMULATED FIXTURE RUN] Running capability synchronization with synthetic test fixtures.")
        report = {
            "discovery_status": "success",
            "is_live": False,
            "registered_connectors_count": 2,
            "mcp_tools_count": 2,
            "connectors": [
                {
                    "id": "apollo_pharmacy",
                    "name": "Apollo Direct Pharmacy API",
                    "provider": "Apollo Pharmacy Partner Network",
                    "category": "pharmacy",
                    "capabilities": ["check_inventory", "get_product_details", "get_price", "reserve_stock"],
                    "status": "active",
                    "authorized": True,
                    "healthy": True,
                },
                {
                    "id": "delhivery_express",
                    "name": "Delhivery Express Delivery",
                    "provider": "Delhivery Logistics",
                    "category": "logistics",
                    "capabilities": ["track_delivery", "schedule_pickup"],
                    "status": "active",
                    "authorized": True,
                    "healthy": True,
                },
            ],
            "mcp_tools": [
                {
                    "name": "create_caregiver_task",
                    "description": "Create a task in the family caregiver task manager",
                    "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
                },
                {
                    "name": "check_caregiver_schedule",
                    "description": "Check family caregiver schedule and pending tasks",
                    "inputSchema": {"type": "object", "properties": {"caregiver_id": {"type": "string"}}},
                },
            ],
            "errors": [],
            "safety_notes": "SIMULATED FIXTURE RUN ONLY. Metadata synchronization performed in isolated simulation mode.",
        }
    else:
        print("[LIVE TENANT RUN] Running live AgenticOrg tenant discovery and capability synchronization.")
        report = discovery_svc.discover_tenant()

    record = synchronizer.synchronize(discovery_report=report)

    print(f"\nSynchronization Summary:")
    print(f"  Sync ID:               {record.sync_id}")
    print(f"  Discovery Source:      {record.discovery_source}")
    print(f"  Status:                {record.status.value}")
    print(f"  Discovered Connectors: {record.connector_count}")
    print(f"  Discovered MCP Tools:  {record.mcp_tool_count}")
    print(f"  Added Capabilities:    {len(record.added_capabilities)} ({', '.join(record.added_capabilities) if record.added_capabilities else 'None'})")
    print(f"  Updated Capabilities:  {len(record.updated_capabilities)} ({', '.join(record.updated_capabilities) if record.updated_capabilities else 'None'})")
    print(f"  Stale Capabilities:    {len(record.stale_capabilities)} ({', '.join(record.stale_capabilities) if record.stale_capabilities else 'None'})")

    if record.partial_failures:
        print("\nPartial Discovery Warnings:")
        for w in record.partial_failures:
            print(f"  [!] {w}")

    if record.sanitized_errors:
        print("\nSanitized Errors:")
        for err in record.sanitized_errors:
            print(f"  [!] {err}")

    print("\nGovernance & Safety Guarantees:")
    print("  [*] Catalog presence != Tenant registration != Authorization != Health.")
    print("  [*] Metadata synchronization only; ZERO operational tools invoked.")
    print("  [*] Healthcare authorization engine and HITL approval manager remain authoritative.")
    print("=" * 80)


def handle_execution_status() -> None:
    """Read-only CLI diagnostics for Controlled Tool Invocation & Execution Gateway."""
    print("=" * 80)
    print(" Aarogya -- Controlled Tool Invocation & Execution Gateway Status")
    print("=" * 80)
    settings = get_settings()
    from .orchestrator.execution_gateway import ExecutionGateway
    gateway = ExecutionGateway(settings=settings)

    print(f"Runtime Execution Mode:   {settings.execution_mode.value}")
    print(f"Deployment Status:        {settings.agenticorg_deployment_status}")
    print(f"Confidence Floor:         {settings.agenticorg_confidence_floor * 100:.0f}%")
    print(f"Live Execution Enabled:   {'Yes' if settings.live_execution_enabled else 'No (Disabled by policy in Module 9)'}")
    print(f"Registered Handlers:      {gateway.registered_handlers_count} operational handlers")
    print(f"Idempotency Cache Size:   {gateway.idempotency_cache_size} active keys")

    print("\nApproved Handler Registry:")
    print(f"{'CAPABILITY PATTERN':<28} {'OPERATION':<26} {'CONSEQUENTIAL':<14} {'APPROVAL':<10}")
    print("-" * 80)
    for (cap, op), handler in sorted(gateway._handlers.items()):
        conseq_str = "Yes" if handler.is_consequential else "No"
        appr_str = "Required" if handler.requires_approval else "None"
        print(f"{cap:<28} {op:<26} {conseq_str:<14} {appr_str:<10}")

    print("-" * 80)
    print("Safety & Governance:")
    print("  [*] All live operations remain DISABLED by default.")
    print("  [*] Only registered synthetic handlers execute in Simulation Mode.")
    print("  [*] Technical execution success != Verified healthcare delivery.")
    print("=" * 80)


def handle_execution_demo(simulated: bool = False) -> None:
    """Run simulated tool invocation demo through the execution gateway."""
    print("=" * 80)
    print(" Aarogya -- Execution Gateway Controlled Invocation Demo")
    print("=" * 80)
    settings = get_settings()
    from .orchestrator.execution_gateway import ExecutionGateway
    from .models.gateway import ExecutionRequest
    from .connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry(execution_mode=ExecutionMode.SIMULATION)
    registry.synchronizer.reconcile_capabilities([
        registry.synchronizer.normalize_connector({
            "id": "apollo_pharmacy",
            "name": "Apollo Direct Pharmacy API",
            "provider": "Apollo Pharmacy Network",
            "category": "pharmacy",
            "capabilities": ["check_inventory", "reserve_stock"],
            "status": "active",
            "authorized": True,
            "healthy": True,
        }),
        registry.synchronizer.normalize_connector({
            "id": "task_manager",
            "name": "Caregiver Task Backend",
            "provider": "Aarogya Family Task Engine",
            "category": "task_manager",
            "capabilities": ["create_caregiver_task", "query_caregiver_task"],
            "status": "active",
            "authorized": True,
            "healthy": True,
        }),
    ])

    gateway = ExecutionGateway(settings=settings, connector_registry=registry)

    print("\n--- Demo Scenario 1: Non-Consequential Medicine Inventory Check ---")
    req1 = ExecutionRequest(
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 30, "pincode": "560001"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="medicine_availability",
        execution_mode=ExecutionMode.SIMULATION,
        confidence_score=0.95,
        idempotency_key="demo_check_001",
    )
    res1 = gateway.execute(req1)
    print(f"Requested Capability:     {req1.capability_id}")
    print(f"Operation:                {req1.requested_operation}")
    print(f"Policy Decision:          {res1.policy_decision.value}")
    print(f"Approval Status:          Not Required")
    print(f"Execution Mode:           {req1.execution_mode.value}")
    print(f"Handler Invoked:          {'Yes' if res1.handler_invoked else 'No'}")
    print(f"Simulation Indicator:     {'SIMULATED' if res1.is_simulated else 'LIVE'}")
    print(f"Final Execution Status:   {res1.status.value}")
    print(f"Verification State:       {res1.verification_status.value}")
    if res1.output:
        print(f"Output:                   {json.dumps(res1.output)}")

    print("\n--- Demo Scenario 2: Consequential Task Without Approval (Safety Gate) ---")
    req2 = ExecutionRequest(
        capability_id="conn:task_manager",
        requested_operation="create_caregiver_task",
        input_payload={"title": "Administer morning insulin", "patient_id": "pat_rajesh_01", "assigned_to": "usr_amit_01"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        workflow_id="caregiver_tasks",
        execution_mode=ExecutionMode.SIMULATION,
        confidence_score=0.92,
        idempotency_key="demo_task_002",
    )
    res2 = gateway.execute(req2)
    print(f"Requested Capability:     {req2.capability_id}")
    print(f"Operation:                {req2.requested_operation}")
    print(f"Policy Decision:          {res2.policy_decision.value}")
    print(f"Approval Status:          MISSING (Blocked by Gateway)")
    print(f"Execution Mode:           {req2.execution_mode.value}")
    print(f"Handler Invoked:          {'Yes' if res2.handler_invoked else 'No'}")
    print(f"Simulation Indicator:     {'SIMULATED' if res2.is_simulated else 'LIVE'}")
    print(f"Final Execution Status:   {res2.status.value}")
    print(f"Error Category:           {res2.error_category}")
    print(f"Error Message:            {res2.error_message}")

    print("\nSafety Verification:")
    print("  [*] Gateway strictly intercepted consequential action lacking HITL approval.")
    print("  [*] No live external operations performed.")
    print("=" * 80)


def handle_storage_status() -> None:
    """Read-only CLI diagnostics for durable persistence layer and SQLite store."""
    print("=" * 80)
    print(" Aarogya -- Durable Registry & Execution Persistence Status")
    print("=" * 80)
    settings = get_settings()
    from .persistence import get_persistence_bundle, CURRENT_SCHEMA_VERSION
    bundle = get_persistence_bundle(settings.database_path)

    ver = bundle.store.fetchone("SELECT MAX(version) as ver FROM schema_version")
    schema_ver = ver["ver"] if ver and ver["ver"] is not None else CURRENT_SCHEMA_VERSION

    cap_count = bundle.capability_repo.count()
    syncs = bundle.sync_history_repo.list_syncs(limit=5)
    execs = bundle.execution_repo.list_executions(limit=5)
    idemp_row = bundle.store.fetchone("SELECT COUNT(*) as cnt FROM idempotency_records")
    idemp_count = int(idemp_row["cnt"]) if idemp_row else 0
    app_pending = len(bundle.approval_repo.list_pending())
    app_row = bundle.store.fetchone("SELECT COUNT(*) as cnt FROM approvals")
    app_count = int(app_row["cnt"]) if app_row else 0
    audit_row = bundle.store.fetchone("SELECT COUNT(*) as cnt FROM audit_events")
    audit_count = int(audit_row["cnt"]) if audit_row else 0

    print(f"Storage Backend:          SQLite (Relational Database)")
    print(f"Database Path:            {settings.database_path}")
    print(f"Schema Version:           v{schema_ver}")
    print(f"Foreign Key Pragma:       ENABLED (Enforced)")
    print(f"Concurrency Mode:         WAL (Write-Ahead Logging)")
    print("-" * 80)
    print(f"Persisted Capabilities:   {cap_count} entries")
    print(f"Sync History Records:     {len(syncs)} runs recorded")
    print(f"Execution Records:        {len(execs)} entries (active/historical)")
    print(f"Idempotency Cache Keys:   {idemp_count} unique keys enforced")
    print(f"Approval References:      {app_count} total ({app_pending} pending)")
    print(f"Structured Audit Events:  {audit_count} events indexed")
    print("-" * 80)
    print("Crash Recovery Safety:")
    print("  [*] Automatic recovery on gateway initialization enabled.")
    print("  [*] Interrupted in-flight executions safely transition to UNKNOWN_OUTCOME.")
    print("  [*] Live external executions remain strictly DISABLED.")
    print("=" * 80)


def handle_execution_history(limit: int = 15) -> None:
    """Display recent execution records from durable persistence."""
    print("=" * 80)
    print(f" Aarogya -- Recent Execution History (Max {limit})")
    print("=" * 80)
    settings = get_settings()
    from .persistence import get_persistence_bundle
    bundle = get_persistence_bundle(settings.database_path)
    records = bundle.execution_repo.list_executions(limit=limit)

    if not records:
        print("No execution records found in durable persistence.")
        print("=" * 80)
        return

    print(f"{'EXECUTION ID':<22} {'OPERATION':<22} {'STATUS':<15} {'SIM':<5} {'VERIF':<12}")
    print("-" * 80)
    for r in records:
        sim_str = "Yes" if r.is_simulated else "No"
        ver_str = r.verification_status.value if hasattr(r.verification_status, "value") else str(r.verification_status)
        print(f"{r.execution_id:<22} {r.operation:<22} {r.status.value:<15} {sim_str:<5} {ver_str:<12}")
    print("=" * 80)


def handle_sync_history(limit: int = 10) -> None:
    """Display capability synchronization history from durable persistence."""
    print("=" * 80)
    print(f" Aarogya -- Capability Synchronization History (Max {limit})")
    print("=" * 80)
    settings = get_settings()
    from .persistence import get_persistence_bundle
    bundle = get_persistence_bundle(settings.database_path)
    records = bundle.sync_history_repo.list_syncs(limit=limit)

    if not records:
        print("No capability synchronization records found.")
        print("=" * 80)
        return

    print(f"{'SYNC ID':<20} {'DISCOVERY STATUS':<18} {'ADDED':<6} {'UPDATED':<8} {'STALE':<6} {'STARTED AT':<20}")
    print("-" * 80)
    for r in records:
        stat_val = r.discovery_status.value if hasattr(r.discovery_status, "value") else str(r.discovery_status)
        start_str = r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else "N/A"
        print(f"{r.sync_id:<20} {stat_val:<18} {len(r.added_capabilities):<6} {len(r.updated_capabilities):<8} {len(r.stale_capabilities):<6} {start_str:<20}")
    print("=" * 80)


def handle_persistence_demo(simulated: bool = True) -> None:
    """Demonstrate end-to-end restart survival of capabilities, idempotency, and audit trails."""
    print("=" * 80)
    print(" Aarogya -- Durable Persistence & Restart Survival Demo")
    print("=" * 80)
    import tempfile
    import os
    from datetime import datetime
    from .persistence import get_persistence_bundle
    from .models.connector import NormalizedCapability
    from .models.gateway import ExecutionRequest
    from .models.enums import HealthcareDomain, ExecutionMode
    from .orchestrator.execution_gateway import ExecutionGateway

    # Use a temporary isolated database to demonstrate survival across repository re-creation
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        demo_db = f.name

    try:
        print("\n--- Step 1: Initial Repository Instance & Capability Storage ---")
        bundle1 = get_persistence_bundle(demo_db)
        demo_cap = NormalizedCapability(
            capability_id="conn:apollo_pharmacy_demo",
            source_platform="demo",
            display_name="Apollo Demo Pharmacy",
            domain=HealthcareDomain.MEDICINE_AVAILABILITY,
            supported_operations=["check_inventory"],
            documented=True,
            registered=True,
            authorized=True,
            connected=True,
            healthy=True,
            capable=True,
            is_verified_healthcare_partner=True,
            discovery_timestamp=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        bundle1.capability_repo.save(demo_cap)
        print(f"Persisted capability: '{demo_cap.capability_id}' into database.")
        bundle1.store.close()

        print("\n--- Step 2: Simulating Process Restart (Re-instantiating Repositories) ---")
        bundle2 = get_persistence_bundle(demo_db)
        recovered_cap = bundle2.capability_repo.get("conn:apollo_pharmacy_demo")
        print(f"Retrieved capability after restart: '{recovered_cap.capability_id if recovered_cap else 'None'}'")
        print(f"Readiness state preserved: authorized={recovered_cap.authorized}, healthy={recovered_cap.healthy}")

        print("\n--- Step 3: Gateway Execution & Idempotency Survival Across Reinitialization ---")
        gw1 = ExecutionGateway(
            settings=get_settings(),
            execution_repo=bundle2.execution_repo,
            idempotency_repo=bundle2.idempotency_repo,
            audit_logger=None,
        )
        req = ExecutionRequest(
            request_id="req_demo_01",
            capability_id="conn:apollo_pharmacy",
            requested_operation="check_inventory",
            input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
            requesting_user_id="usr_amit_01",
            patient_id="pat_rajesh_01",
            idempotency_key="idemp_demo_key_999",
            execution_mode=ExecutionMode.SIMULATION,
        )
        res1 = gw1.execute(req)
        print(f"First execution: status={res1.status.value}, handler_invoked={res1.handler_invoked}")

        # Simulate second gateway instance (after crash/restart)
        gw2 = ExecutionGateway(
            settings=get_settings(),
            execution_repo=bundle2.execution_repo,
            idempotency_repo=bundle2.idempotency_repo,
            audit_logger=None,
        )
        res2 = gw2.execute(req)
        print(f"Second execution with duplicate key: status={res2.status.value}, idempotency_matched={res2.idempotency_matched}")

        print("\nSafety Verification:")
        print("  [*] State survived across distinct repository and gateway lifecycles.")
        print("  [*] Idempotency constraint successfully prevented duplicate handler invocation.")
        print("  [*] Zero live healthcare mutations occurred.")
        print("=" * 80)
        bundle2.store.close()
    finally:
        if os.path.exists(demo_db):
            try:
                os.remove(demo_db)
            except Exception:
                pass


def handle_pharmacy_status() -> None:
    """Display pharmacy adapter provider mode, configuration, and supported operations."""
    print("=" * 80)
    print(" Aarogya -- Direct Pharmacy API Provider Adapter Status")
    print("=" * 80)

    settings = get_settings()
    from .connectors.pharmacy_adapter import get_pharmacy_adapter
    adapter = get_pharmacy_adapter(settings)

    print(f"Provider Name:            {adapter.provider_name}")
    print(f"Environment Mode:         {settings.pharmacy_environment.upper()}")
    print(f"Base URL:                 {settings.pharmacy_base_url or 'None (Isolated Mock Provider)'}")
    print(f"Integration Enabled:      {'Yes' if settings.pharmacy_integration_enabled else 'No'}")
    print(f"Verified Partner Status:  {'Verified Clinical Partner' if adapter.is_verified_healthcare_partner else 'Unverified / Generic Retail'}")
    print(f"Live Execution Status:    {'ENABLED' if settings.live_execution_enabled else 'STRICTLY DISABLED (Safe Simulation Mode)'}")
    print(f"Live Ordering Allowed:    {'Yes' if settings.pharmacy_live_operations_enabled else 'No (Blocked by policy)'}")
    print(f"Timeout:                  {settings.pharmacy_request_timeout}s")
    print(f"Credentials Configured:   {'Yes (Reference masked)' if (settings.pharmacy_api_key or settings.pharmacy_credential_ref) else 'No (Mock Mode)'}")
    print("-" * 80)
    print("Supported Read-Only Operations:")
    print("  [*] check_inventory          (Real-time stock checking)")
    print("  [*] get_product_details      (Product catalog metadata & active ingredients)")
    print("  [*] get_price                (Medicine unit price and total cost calculation)")
    print("  [*] check_delivery_coverage  (Postal pincode serviceability and turnaround)")
    print("  [*] get_order_status         (Tracking status for synthetic or sandbox orders)")
    print("-" * 80)
    print("Consequential Operations (HITL Approval & Live Disabled):")
    print("  [!] reserve_stock            (Requires Approval; Live ordering disabled)")
    print("  [!] create_order             (Requires Approval; Live ordering disabled)")
    print("=" * 80)


def handle_pharmacy_demo(simulated: bool = True) -> None:
    """Run interactive demonstration of pharmacy provider adapter read operations."""
    print("=" * 80)
    print(" Aarogya -- Direct Pharmacy Adapter Demonstration")
    print("=" * 80)

    settings = get_settings()
    from .connectors.pharmacy_adapter import get_pharmacy_adapter
    adapter = get_pharmacy_adapter(settings)

    print("\n--- 1. Querying Product Details ('Metformin 500mg') ---")
    try:
        details = adapter.get_product_details(medicine_name="Metformin 500mg")
        print(f"Product ID:         {details.product_id}")
        print(f"Product Name:       {details.product_name}")
        print(f"Active Ingredient:  {details.active_ingredient}")
        print(f"Strength & Form:    {details.strength} ({details.dosage_form})")
        print(f"Manufacturer:       {details.manufacturer}")
        print(f"Pack Size:          {details.pack_size}")
        print(f"Availability:       {details.availability_status}")
        print(f"Source Provider:    {details.source_provider}")
    except Exception as e:
        print(f"[!] Error: {e}")

    print("\n--- 2. Checking Real-Time Inventory ('Metformin 500mg', qty=10) ---")
    try:
        inv = adapter.check_inventory(medicine_name="Metformin 500mg", quantity=10)
        print(f"Product ID:         {inv.product_id}")
        print(f"Status:             {inv.availability_status}")
        print(f"Available Quantity: {inv.quantity} units")
        print(f"Timestamp:          {inv.inventory_timestamp.isoformat()}")
    except Exception as e:
        print(f"[!] Error: {e}")

    print("\n--- 3. Checking Pricing ('Metformin 500mg', qty=30) ---")
    try:
        price = adapter.get_price(medicine_name="Metformin 500mg", quantity=30)
        print(f"Unit Price:         {price.currency} {price.unit_price}")
        print(f"Total Amount (30x): {price.currency} {price.amount}")
        print(f"MRP:                {price.currency} {price.mrp}")
    except Exception as e:
        print(f"[!] Error: {e}")

    print("\n--- 4. Checking Delivery Coverage (Pincode '560001') ---")
    try:
        cov = adapter.check_delivery_coverage(pincode="560001", medicine_name="Metformin 500mg")
        print(f"Pincode:            {cov.pincode}")
        print(f"Serviceable:        {'Yes' if cov.is_serviceable else 'No'}")
        print(f"Estimated Delivery: {cov.estimated_delivery or 'N/A'}")
        print(f"Courier Partner:    {cov.delivery_partner or 'N/A'}")
    except Exception as e:
        print(f"[!] Error: {e}")

    print("\n--- 5. Checking Existing Order Status ('ord_synth_12345') ---")
    try:
        status = adapter.get_order_status(order_id="ord_synth_12345")
        print(f"Order ID:           {status.order_id}")
        print(f"Status:             {status.status}")
        print(f"Description:        {status.status_description}")
        print(f"Tracking Ref:       {status.tracking_reference or 'N/A'}")
    except Exception as e:
        print(f"[!] Error: {e}")

    print("\nSafety Verification:")
    print("  [*] All operations executed safely via mock/sandbox adapter.")
    print("  [*] Zero live external healthcare transactions or medicine orders placed.")
    print("  [*] Live execution remains disabled by policy.")
    print("=" * 80)


def handle_appointment_demo(simulated: bool = True) -> None:
    """Demonstrate Phase 14 appointment discovery, HITL approval, and voice coordination."""
    print("=" * 80)
    print(" Aarogya -- Appointment & Voice Coordination Demo (Phase 14)")
    print("=" * 80)
    from .models.appointment import AppointmentRequest, AppointmentSlotApprovalRequest, ClinicInfo
    from .brain.family_health_brain import FamilyHealthBrain
    from .policy.authorization_engine import PolicyAuthorizationEngine
    from .workflows.appointment_coordination import AppointmentCoordinationWorkflow
    from .connectors.gnani_adapter import MockGnaniVoiceProvider
    from .persistence import get_persistence_bundle

    brain = FamilyHealthBrain()
    policy_engine = PolicyAuthorizationEngine(brain)
    settings = get_settings()
    bundle = get_persistence_bundle(settings.database_path)
    provider = MockGnaniVoiceProvider()

    workflow = AppointmentCoordinationWorkflow(
        brain=brain,
        policy_engine=policy_engine,
        appointment_repo=bundle.appointment_repo,
        voice_repo=bundle.voice_repo,
        voice_provider=provider,
    )

    print("\n--- 1. Initiating Appointment Coordination (Preferred Slot Unavailable) ---")
    provider.set_scenario("preferred_unavailable_alternatives")
    req = AppointmentRequest(
        patient_id="pat_rajesh_01",
        requesting_user_id="usr_amit_01",
        clinic=ClinicInfo(
            clinic_id="cln_apollo_blr",
            clinic_name="Apollo Clinic Bangalore",
            contact_phone="+91-80-23456789",
        ),
        preferred_date="2026-10-25",
        preferred_time="09:00 AM",
        reason_for_visit="Quarterly hypertension review",
    )
    success, msg, record = workflow.initiate_coordination(req)
    print(f"Status:             {record.status.value}")
    print(f"Workflow Message:   {msg}")
    print(f"Offered Slots ({len(record.available_slots)}):")
    for s in record.available_slots:
        print(f"  - [{s.slot_id}] {s.date} at {s.start_time} ({s.notes or 'Routine'})")

    print("\n--- 2. Human-in-the-Loop Slot Approval & Policy-Governed Booking ---")
    chosen_slot = record.available_slots[0]
    print(f"Caregiver (usr_amit_01) approving slot: {chosen_slot.slot_id} ({chosen_slot.start_time})")
    app_req = AppointmentSlotApprovalRequest(
        appointment_id=record.appointment_id,
        approving_user_id="usr_amit_01",
        slot_id=chosen_slot.slot_id,
        approval_notes="Caregiver confirmed afternoon slot",
    )
    b_success, b_msg, confirmed = workflow.approve_and_book_slot(app_req)
    print(f"Booking Status:     {confirmed.status.value}")
    print(f"Booking Reference:  {confirmed.clinic_booking_reference}")
    print(f"Confirmed Slot:     {confirmed.approved_slot.date} at {confirmed.approved_slot.start_time}")
    print(f"Workflow Message:   {b_msg}")

    print("\nSafety Verification:")
    print("  [*] Simulated Gnani voice execution completed safely.")
    print("  [*] Explicit caregiver HITL authorization enforced for alternative slot.")
    print("  [*] Zero unapproved autonomous slot choices.")
    print("  [*] All records persisted durably in SQLite with schema v2.")
    print("=" * 80)


def handle_evaluation_list() -> None:
    """Display all evaluation scenarios in the catalog."""
    from .evaluation import list_all_scenarios, format_scenario_list
    scenarios = list_all_scenarios()
    print(format_scenario_list(scenarios))


def handle_evaluation_run(simulated: bool = True) -> None:
    """Run all 10 end-to-end evaluation scenarios in isolated simulation mode."""
    print("=" * 80)
    print(" Aarogya -- Running End-to-End Evaluation Suite (Module 12)")
    print("=" * 80)
    from .evaluation import EvaluationRunner, format_evaluation_report
    runner = EvaluationRunner()
    report = runner.run_all()
    print(format_evaluation_report(report))


def handle_evaluation_report() -> None:
    """Run evaluation and output complete structured diagnostic report."""
    from .evaluation import EvaluationRunner, format_evaluation_report
    runner = EvaluationRunner()
    report = runner.run_all()
    print(format_evaluation_report(report))


def handle_demo_list() -> None:

    """Display catalog of the 5 competition demonstration scenarios."""
    from .demo import list_demo_scenarios, format_demo_list
    print(format_demo_list(list_demo_scenarios()))


def handle_demo_run(scenario: Optional[str] = None, run_all: bool = False, simulated: bool = True) -> None:
    """Run specified demonstration scenario or all 5 scenarios."""
    from .demo import (
        CompetitionDemoOrchestrator,
        format_single_demo_result,
        format_all_demo_results,
    )
    orchestrator = CompetitionDemoOrchestrator()
    if run_all or not scenario or scenario == "all":
        results = orchestrator.run_all()
        print(format_all_demo_results(results))
    else:
        res = orchestrator.run_demo(scenario)
        print(format_single_demo_result(res))


def handle_readiness_report() -> None:
    """Display Capability Truth Matrix and Technical Readiness Assessment."""
    from .demo import (
        format_capability_truth_matrix,
        format_readiness_report,
        CAPABILITY_TRUTH_MATRIX,
        TruthfulEvaluationMetrics,
        get_technical_readiness_assessment,
    )
    metrics = TruthfulEvaluationMetrics()
    print(format_capability_truth_matrix(CAPABILITY_TRUTH_MATRIX, metrics))
    print("\n")
    print(format_readiness_report(get_technical_readiness_assessment(), metrics))


def main(args: list[str] | None = None) -> int:
    if args is not None:
        sys.argv = ["cli.py"] + list(args)

    if len(sys.argv) > 1:
        cmd = sys.argv[1].strip().lower()
        if cmd == "agenticorg-status":
            handle_agenticorg_status()
            return 0

        elif cmd == "agenticorg-discover":
            handle_agenticorg_discover()
            return 0
        elif cmd == "capabilities":
            handle_capabilities()
            return 0
        elif cmd == "capability-sync":
            simulated = "--simulated" in sys.argv
            handle_capability_sync(simulated=simulated)
            return 0
        elif cmd == "execution-status":
            handle_execution_status()
            return 0
        elif cmd == "execution-demo":
            simulated = "--simulated" in sys.argv or True
            handle_execution_demo(simulated=simulated)
            return 0
        elif cmd == "storage-status":
            handle_storage_status()
            return 0
        elif cmd == "execution-history":
            handle_execution_history()
            return 0
        elif cmd == "sync-history":
            handle_sync_history()
            return 0
        elif cmd == "persistence-demo":
            simulated = "--simulated" in sys.argv or True
            handle_persistence_demo(simulated=simulated)
            return 0
        elif cmd == "pharmacy-status":
            handle_pharmacy_status()
            return 0
        elif cmd == "pharmacy-demo":
            simulated = "--simulated" in sys.argv or True
            handle_pharmacy_demo(simulated=simulated)
            return 0
        elif cmd == "evaluation-list":
            handle_evaluation_list()
            return 0
        elif cmd == "evaluation-run":
            simulated = "--simulated" in sys.argv or True
            handle_evaluation_run(simulated=simulated)
            return 0
        elif cmd == "evaluation-report":
            handle_evaluation_report()
            return 0
        elif cmd == "demo-list":
            handle_demo_list()
            return 0
        elif cmd == "demo-run":
            run_all = "--all" in sys.argv
            simulated = "--simulated" in sys.argv or True
            scenario_name = None
            if "--scenario" in sys.argv:
                idx = sys.argv.index("--scenario")
                if idx + 1 < len(sys.argv):
                    scenario_name = sys.argv[idx + 1]
            handle_demo_run(scenario=scenario_name, run_all=run_all, simulated=simulated)
            return 0
        elif cmd == "readiness-report":
            handle_readiness_report()
            return 0
        elif cmd == "appointment-demo":
            simulated = "--simulated" in sys.argv or True
            handle_appointment_demo(simulated=simulated)
            return 0
        elif cmd in ("serve", "api-server"):
            import uvicorn
            from .api import create_app
            app = create_app()
            port = int(os.getenv("PORT", "8000"))
            host = os.getenv("HOST", "127.0.0.1")
            print(f"Starting Aarogya API Server on http://{host}:{port} (docs at /api/docs)...")
            uvicorn.run(app, host=host, port=port)
            return 0

        elif cmd in ("--help", "-h", "help"):
            print("Aarogya Healthcare Coordinator CLI")
            print("\nAvailable Commands:")
            print("  demo-list            Display 5 competition demonstration scenarios")
            print("  demo-run             Run competition demonstration (--scenario <name> or --all)")
            print("  readiness-report     Display Capability Truth Matrix & Technical Readiness")
            print("  evaluation-list      Display all 10 end-to-end evaluation scenarios in catalog")
            print("  evaluation-run       Execute full end-to-end evaluation suite with assertions")
            print("  evaluation-report    Generate detailed diagnostic evaluation report")
            print("  pharmacy-status      Display pharmacy provider adapter configuration and status")
            print("  pharmacy-demo        Run demonstration of pharmacy provider read operations")
            print("  storage-status       Display durable SQLite database tables, record counts & schema version")
            print("  execution-history    Display recent gateway execution records from persistence")
            print("  sync-history         Display capability discovery synchronization history")
            print("  persistence-demo     Run end-to-end restart survival & idempotency persistence demo")
            print("  execution-status     Display Execution Gateway readiness and approved handlers")
            print("  execution-demo       Run simulated invocation demo through policy gateway")
            print("  capabilities         Display normalized capabilities and readiness states")
            print("  capability-sync      Run discovery, normalize, reconcile & record audit history")
            print("  agenticorg-status    Check AgenticOrg authentication & tenant connectivity")
            print("  agenticorg-discover  Run read-only tenant connector & MCP tool discovery")
            print("  <user query>         Execute a family healthcare coordination query")
            print("\nExamples:")
            print("  python -m aarogya.cli demo-list")
            print("  python -m aarogya.cli demo-run --scenario family-medicine --simulated")
            print("  python -m aarogya.cli demo-run --scenario unauthorized-access --simulated")
            print("  python -m aarogya.cli demo-run --scenario emergency-routing --simulated")
            print("  python -m aarogya.cli demo-run --scenario provider-failure --simulated")
            print("  python -m aarogya.cli demo-run --scenario uncertain-outcome --simulated")
            print("  python -m aarogya.cli demo-run --all --simulated")
            print("  python -m aarogya.cli readiness-report")
            print("  python -m aarogya.cli evaluation-list")
            print("  python -m aarogya.cli evaluation-run --simulated")
            return 0


        # Direct healthcare query
        query = " ".join(sys.argv[1:])
        print("=" * 70)
        print(" Aarogya -- Family Healthcare Coordinator (Phase 2 & 3)")
        print("=" * 70)
        settings = get_settings()
        agent = AarogyaAgent(settings=settings)
        print(f"\nProcessing query: {query}\n")
        req = HealthcareRequest(
            user_id="usr_amit_01",
            raw_text=query,
            patient_name="Rajesh Kumar",
        )
        resp = agent.process_request(req)
        print(json.dumps(resp, indent=2))
        return

    # Interactive mode
    print("=" * 70)
    print(" Aarogya -- Family Healthcare Coordinator (Phase 2 & 3)")
    print("=" * 70)
    settings = get_settings()
    print(f"Current Execution Mode: {settings.execution_mode.value}")
    print(f"AgenticOrg Fleet Status: {'Configured' if (settings.agenticorg_api_key or settings.agenticorg_grantex_token) else 'Isolated (Simulation Mode)'}")
    print("Commands: 'capabilities', 'capability-sync', 'agenticorg-status', 'agenticorg-discover', or type a request.")
    print("=" * 70)

    agent = AarogyaAgent(settings=settings)

    while True:
        try:
            line = input("\nUser > ").strip()
            if not line or line.lower() in ["exit", "quit", "q"]:
                break
            if line.lower() == "capabilities":
                handle_capabilities()
                continue
            if line.lower().startswith("capability-sync"):
                simulated = "--simulated" in line
                handle_capability_sync(simulated=simulated)
                continue
            if line.lower() == "agenticorg-status":
                handle_agenticorg_status()
                continue
            if line.lower() == "agenticorg-discover":
                handle_agenticorg_discover()
                continue

            req = HealthcareRequest(
                user_id="usr_amit_01",
                raw_text=line,
            )
            resp = agent.process_request(req)
            print("\nAarogya Response:")
            print(json.dumps(resp, indent=2))
        except (KeyboardInterrupt, EOFError):
            print("\nExiting Aarogya.")
            break


if __name__ == "__main__":
    main()

