"""Module 8: Connector & MCP Capability Synchronization Engine.

Normalizes tenant-discovered connector and MCP tool metadata into Aarogya's
canonical capability model, classifies capabilities into healthcare domains,
safely reconciles registry states, and evaluates operational readiness against
strict healthcare safety and authorization boundaries.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

from ..config import Settings, get_settings
from ..models.connector import (
    NormalizedCapability,
    SyncHistoryRecord,
    CapabilityPolicyEvaluation,
    ConnectorStatus,
)
from ..models.enums import (
    HealthcareDomain,
    CapabilityPolicyDecision,
    DiscoveryStatus,
    AuditEventType,
    ExecutionMode,
)
from ..orchestrator.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Classification Rules (Metadata-Based & Conservative)
# ------------------------------------------------------------------------------

# Direct pharmacy operation identifiers (Section 9)
DIRECT_PHARMACY_OPERATIONS: Set[str] = {
    "check_inventory",
    "get_product_details",
    "get_price",
    "check_delivery_coverage",
    "reserve_stock",
    "create_order",
    "get_order_status",
    "check_medicine_availability",
}

# Generic commerce indicators that must NOT be confused with verified pharmacy partners
GENERIC_COMMERCE_INDICATORS: Set[str] = {
    "shopify",
    "woocommerce",
    "magento",
    "generic_retail",
    "ecommerce",
    "marketplace",
    "general_store",
}

PHARMACY_NAME_INDICATORS: Set[str] = {
    "pharmacy",
    "pharma",
    "medplus",
    "apollo_pharmacy",
    "chemist",
    "prescription_dispensary",
    "medicine_stock",
}


def classify_capability(
    display_name: str,
    description: str,
    operations: List[str],
    provider_name: str = "",
    category: str = "",
) -> Tuple[HealthcareDomain, bool]:
    """Conservatively classify a discovered tool into a healthcare domain.

    Returns:
        (domain, is_verified_healthcare_partner)
    """
    text_to_check = f"{display_name} {description} {provider_name} {category} {' '.join(operations)}".lower()

    # 1. Generic Commerce Exclusion Check:
    # A generic commerce tool must NEVER be treated as a verified pharmacy partner
    is_generic_commerce = any(ind in text_to_check for ind in GENERIC_COMMERCE_INDICATORS)

    # 2. Medicine Availability & Ordering Check
    has_pharmacy_indicator = any(p in text_to_check for p in PHARMACY_NAME_INDICATORS)
    has_medicine_term = any(m in text_to_check for m in ["medicine", "medication", "prescription", "rx", "drug"])

    # If it is generic commerce and lacks explicit pharmacy accreditation, classify as UNKNOWN
    if is_generic_commerce and not has_pharmacy_indicator:
        return HealthcareDomain.UNKNOWN, False

    # Check for direct pharmacy operations
    if has_pharmacy_indicator or has_medicine_term:
        if any(op in text_to_check for op in ["order", "purchase", "create_order", "place_order"]):
            return HealthcareDomain.MEDICINE_ORDERING, has_pharmacy_indicator
        if any(op in text_to_check for op in ["inventory", "stock", "availability", "check_inventory", "get_price"]):
            return HealthcareDomain.MEDICINE_AVAILABILITY, has_pharmacy_indicator

    # 3. Caregiver Tasks Check
    if any(t in text_to_check for t in ["caregiver", "caregiver_task", "family_task", "patient_task", "task_engine"]):
        return HealthcareDomain.CAREGIVER_TASKS, True

    # 4. Doctor / Appointment Check
    if any(a in text_to_check for a in ["appointment", "doctor", "consultation", "clinic", "slot"]):
        if any(w in text_to_check for w in ["book", "schedule", "reserve"]):
            return HealthcareDomain.APPOINTMENT_BOOKING, False
        return HealthcareDomain.APPOINTMENT_DISCOVERY, False

    # 5. Payments Check
    if any(p in text_to_check for p in ["payment", "pine_labs", "pos", "transaction", "copay", "checkout"]):
        return HealthcareDomain.PAYMENTS, "pine" in text_to_check

    # 6. Logistics Check
    if any(l in text_to_check for l in ["logistics", "delhivery", "courier", "dispatch", "shipment", "delivery"]):
        return HealthcareDomain.LOGISTICS, "delhivery" in text_to_check

    # 7. Voice / Telephony Check
    if any(v in text_to_check for v in ["voice", "telephony", "gnani", "speech", "call", "audio"]):
        return HealthcareDomain.VOICE_COMMUNICATION, "gnani" in text_to_check

    # 8. Document Ingestion Check
    if any(d in text_to_check for d in ["document", "prescription_upload", "ocr", "ehr_import", "ingestion"]):
        return HealthcareDomain.DOCUMENT_INGESTION, False

    # Conservative Fallback: Unknown tools must remain UNKNOWN
    return HealthcareDomain.UNKNOWN, False


class CapabilitySynchronizer:
    """Synchronizes discovered connector and MCP metadata into Aarogya's capability registry."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        audit_logger: Optional[AuditLogger] = None,
        capability_repo: Optional[Any] = None,
        sync_history_repo: Optional[Any] = None,
    ):
        self.settings = settings or get_settings()
        self.audit_logger = audit_logger or AuditLogger(
            log_file=self.settings.audit_log_file,
            redact_sensitive=self.settings.redact_sensitive_data,
        )
        self.capability_repo = capability_repo
        self.sync_history_repo = sync_history_repo
        self._capabilities: Dict[str, NormalizedCapability] = {}
        self._sync_history: List[SyncHistoryRecord] = []

        # Load persisted capabilities if repository is available
        if self.capability_repo:
            try:
                for cap in self.capability_repo.list_all(include_stale=True):
                    self._capabilities[cap.capability_id] = cap
            except Exception as e:
                logger.warning("Could not load capabilities from persistence: %s", str(e))

    @property
    def capabilities(self) -> Dict[str, NormalizedCapability]:
        return dict(self._capabilities)

    @property
    def sync_history(self) -> List[SyncHistoryRecord]:
        if self.sync_history_repo:
            try:
                records = self.sync_history_repo.list_syncs()
                if records:
                    return records
            except Exception as e:
                logger.warning("Could not fetch sync history from persistence: %s", str(e))
        return list(self._sync_history)

    def normalize_connector(self, item: Dict[str, Any]) -> NormalizedCapability:
        """Transform a raw tenant connector dict into a NormalizedCapability without inventing metadata."""
        raw_id = str(item.get("id") or item.get("name") or "unnamed_connector").strip()
        cap_id = f"conn:{raw_id}" if not raw_id.startswith("conn:") else raw_id
        display_name = str(item.get("name") or item.get("provider") or raw_id)
        description = str(item.get("description") or "")
        provider = str(item.get("provider") or item.get("provider_name") or "")
        category = str(item.get("category") or "")
        status_val = str(item.get("status") or "").lower()

        # Extract operations
        ops: List[str] = []
        if "capabilities" in item and isinstance(item["capabilities"], list):
            ops.extend(str(o) for o in item["capabilities"])
        elif "supported_capabilities" in item and isinstance(item["supported_capabilities"], list):
            ops.extend(str(o) for o in item["supported_capabilities"])
        elif "operations" in item and isinstance(item["operations"], list):
            ops.extend(str(o) for o in item["operations"])

        # Classify domain
        domain, is_verified_partner = classify_capability(
            display_name=display_name,
            description=description,
            operations=ops,
            provider_name=provider,
            category=category,
        )

        # Independent states: keep None if not explicitly present
        connected: Optional[bool] = None
        if status_val == "active":
            connected = True
        elif status_val == "inactive":
            connected = False

        healthy: Optional[bool] = None
        if "healthy" in item:
            healthy = bool(item["healthy"])
        elif status_val == "active":
            healthy = True

        authorized: Optional[bool] = None
        if "authorized" in item:
            authorized = bool(item["authorized"])

        capable: Optional[bool] = True if ops else None

        clean_meta = {
            k: v for k, v in item.items()
            if not any(s in k.lower() for s in ["key", "token", "secret", "auth", "password"])
        }

        return NormalizedCapability(
            capability_id=cap_id,
            source_platform="agenticorg",
            tenant_connector_id=raw_id,
            mcp_tool_id=None,
            display_name=display_name,
            description=description,
            domain=domain,
            category=category or None,
            supported_operations=ops,
            input_schema=item.get("input_schema") or item.get("inputSchema"),
            output_schema=item.get("output_schema") or item.get("outputSchema"),
            source_metadata_version=item.get("version"),
            documented=True,
            registered=True,
            authorized=authorized,
            connected=connected,
            healthy=healthy,
            capable=capable,
            is_verified_healthcare_partner=is_verified_partner,
            is_stale=False,
            raw_metadata=clean_meta,
        )

    def normalize_mcp_tool(self, tool: Dict[str, Any]) -> NormalizedCapability:
        """Transform a raw MCP tool dict into a NormalizedCapability without inventing metadata."""
        tool_name = str(tool.get("name") or "unnamed_mcp_tool").strip()
        cap_id = f"mcp:{tool_name}"
        description = str(tool.get("description") or "")
        input_schema = tool.get("inputSchema") or tool.get("input_schema")
        output_schema = tool.get("outputSchema") or tool.get("output_schema")

        # In MCP, the tool name is its primary supported operation
        operations = [tool_name]

        # Classify domain
        domain, is_verified_partner = classify_capability(
            display_name=tool_name,
            description=description,
            operations=operations,
            provider_name="MCP Server",
        )

        clean_meta = {
            k: v for k, v in tool.items()
            if not any(s in k.lower() for s in ["key", "token", "secret", "auth", "password"])
        }

        return NormalizedCapability(
            capability_id=cap_id,
            source_platform="agenticorg",
            tenant_connector_id=None,
            mcp_tool_id=tool_name,
            display_name=tool_name,
            description=description,
            domain=domain,
            category="mcp_tool",
            supported_operations=operations,
            input_schema=input_schema,
            output_schema=output_schema,
            documented=True,
            registered=True,
            authorized=None,    # Unknown without explicit tenant RBAC proof
            connected=True,     # Active on discovered MCP endpoint
            healthy=None,       # Unknown without explicit health query
            capable=True,
            is_verified_healthcare_partner=is_verified_partner,
            is_stale=False,
            raw_metadata=clean_meta,
        )

    def reconcile_capabilities(
        self,
        discovered_items: List[NormalizedCapability],
        discovery_source: str = "tenant_discovery",
        partial_category: Optional[str] = None,
    ) -> Tuple[List[str], List[str], List[str]]:
        """Reconcile fresh discovered capabilities with the local registry.

        Returns:
            (added_ids, updated_ids, stale_ids)

        Safety Guarantees:
        - Deduplicates using stable capability_id.
        - Preserves locally managed `authorized` status on existing capabilities.
        - Marks removed capabilities as `is_stale = True` instead of deleting them.
        - Partial discovery updates only its category, leaving the other category untouched.
        """
        now = datetime.utcnow()
        added_ids: List[str] = []
        updated_ids: List[str] = []
        stale_ids: List[str] = []

        # Deduplicate incoming items by capability_id
        incoming_by_id: Dict[str, NormalizedCapability] = {}
        for item in discovered_items:
            incoming_by_id[item.capability_id] = item

        # 1. Update existing or insert new
        for cap_id, incoming in incoming_by_id.items():
            if cap_id in self._capabilities:
                existing = self._capabilities[cap_id]
                # Preserve locally managed authorization if existing was already set
                preserved_authorized = existing.authorized if existing.authorized is not None else incoming.authorized

                # Update metadata while preserving local governance
                existing.display_name = incoming.display_name
                existing.description = incoming.description
                existing.domain = incoming.domain
                existing.category = incoming.category
                existing.supported_operations = incoming.supported_operations
                existing.input_schema = incoming.input_schema
                existing.output_schema = incoming.output_schema
                existing.last_seen_at = now
                existing.registered = incoming.registered
                existing.connected = incoming.connected
                existing.healthy = incoming.healthy
                existing.capable = incoming.capable
                existing.is_verified_healthcare_partner = incoming.is_verified_healthcare_partner
                existing.authorized = preserved_authorized
                existing.is_stale = False
                existing.raw_metadata = incoming.raw_metadata
                updated_ids.append(cap_id)
            else:
                incoming.last_seen_at = now
                self._capabilities[cap_id] = incoming
                added_ids.append(cap_id)

        # 2. Mark removed capabilities as stale
        # If partial_category is specified (e.g. 'connectors' or 'mcp'), only check removal within that category
        for cap_id, cap in self._capabilities.items():
            if partial_category:
                if partial_category == "connectors" and not cap_id.startswith("conn:"):
                    continue
                if partial_category == "mcp" and not cap_id.startswith("mcp:"):
                    continue

            if cap_id not in incoming_by_id:
                if not cap.is_stale:
                    cap.is_stale = True
                    stale_ids.append(cap_id)
                    self.audit_logger.log(
                        event_type=AuditEventType.CAPABILITY_MARKED_STALE,
                        status="stale",
                        details=f"Capability '{cap_id}' not seen in fresh discovery; marked stale.",
                        execution_mode=self.settings.execution_mode,
                    )

        # Persist to durable capability repository if configured
        if self.capability_repo:
            try:
                items_to_save = [self._capabilities[cid] for cid in (added_ids + updated_ids) if cid in self._capabilities]
                if items_to_save:
                    self.capability_repo.save_all(items_to_save)
                for sid in stale_ids:
                    self.capability_repo.mark_stale(sid)
            except Exception as e:
                logger.error("Failed to persist reconciled capabilities: %s", str(e))

        return added_ids, updated_ids, stale_ids

    def synchronize(
        self,
        discovery_report: Optional[Dict[str, Any]] = None,
        discovery_service: Optional[Any] = None,
    ) -> SyncHistoryRecord:
        """Execute a full synchronization cycle and record history.

        This method is strictly read-only: it does NOT invoke any operational tools.
        """
        started_at = datetime.utcnow()
        sync_id = f"sync_{uuid.uuid4().hex[:10]}"

        self.audit_logger.log(
            event_type=AuditEventType.CAPABILITY_SYNC_STARTED,
            status="started",
            details=f"Starting capability synchronization cycle {sync_id}.",
            execution_mode=self.settings.execution_mode,
        )

        # Retrieve discovery report if not provided
        report = discovery_report
        if report is None and discovery_service is not None:
            report = discovery_service.discover_tenant()

        if report is None:
            completed_at = datetime.utcnow()
            record = SyncHistoryRecord(
                sync_id=sync_id,
                started_at=started_at,
                completed_at=completed_at,
                discovery_source="none",
                status=DiscoveryStatus.FAILED,
                sanitized_errors=["No discovery report or service provided for synchronization."],
            )
            self._sync_history.append(record)
            if self.sync_history_repo:
                try:
                    self.sync_history_repo.record_sync(record)
                except Exception as e:
                    logger.error("Failed to persist sync history: %s", str(e))
            self.audit_logger.log(
                event_type=AuditEventType.CAPABILITY_SYNC_FAILED,
                status="failed",
                details="Synchronization failed: no discovery input available.",
                execution_mode=self.settings.execution_mode,
            )
            return record

        status_str = report.get("discovery_status", DiscoveryStatus.FAILED.value)
        status_enum = DiscoveryStatus(status_str) if status_str in DiscoveryStatus._value2member_map_ else DiscoveryStatus.FAILED

        # Rule 10: Failed discovery must NOT overwrite previously successful registry
        if status_enum == DiscoveryStatus.FAILED:
            completed_at = datetime.utcnow()
            errors = list(report.get("errors", []))
            record = SyncHistoryRecord(
                sync_id=sync_id,
                started_at=started_at,
                completed_at=completed_at,
                discovery_source="agenticorg_tenant",
                status=DiscoveryStatus.FAILED,
                sanitized_errors=errors,
            )
            self._sync_history.append(record)
            if self.sync_history_repo:
                try:
                    self.sync_history_repo.record_sync(record)
                except Exception as e:
                    logger.error("Failed to persist sync history: %s", str(e))
            self.audit_logger.log(
                event_type=AuditEventType.CAPABILITY_SYNC_FAILED,
                status="failed",
                details=f"Discovery failed; existing registry state preserved without modification: {'; '.join(errors)}",
                execution_mode=self.settings.execution_mode,
            )
            return record

        # Rule 11: Partial discovery handling
        partial_category = None
        partial_failures = []
        if status_enum == DiscoveryStatus.PARTIAL:
            errors = report.get("errors", [])
            partial_failures.extend(errors)
            if any("mcp" in e.lower() for e in errors):
                partial_category = "connectors"  # Only connectors succeeded
            elif any("connector" in e.lower() for e in errors):
                partial_category = "mcp"         # Only MCP succeeded

        # Normalize incoming connectors and MCP tools
        normalized_items: List[NormalizedCapability] = []
        raw_connectors = report.get("connectors", [])
        raw_mcp_tools = report.get("mcp_tools", [])

        if partial_category != "mcp":
            for c in raw_connectors:
                normalized_items.append(self.normalize_connector(c))

        if partial_category != "connectors":
            for t in raw_mcp_tools:
                normalized_items.append(self.normalize_mcp_tool(t))

        # Reconcile capabilities
        added, updated, stale = self.reconcile_capabilities(
            discovered_items=normalized_items,
            discovery_source="agenticorg_tenant",
            partial_category=partial_category,
        )

        completed_at = datetime.utcnow()
        sync_record = SyncHistoryRecord(
            sync_id=sync_id,
            started_at=started_at,
            completed_at=completed_at,
            discovery_source="agenticorg_tenant",
            connector_count=len(raw_connectors),
            mcp_tool_count=len(raw_mcp_tools),
            added_capabilities=added,
            updated_capabilities=updated,
            stale_capabilities=stale,
            partial_failures=partial_failures,
            sanitized_errors=list(report.get("errors", [])),
            status=status_enum,
        )
        self._sync_history.append(sync_record)
        if self.sync_history_repo:
            try:
                self.sync_history_repo.record_sync(sync_record)
            except Exception as e:
                logger.error("Failed to persist sync history: %s", str(e))

        self.audit_logger.log(
            event_type=AuditEventType.CAPABILITY_SYNC_COMPLETED,
            status=status_enum.value,
            details=(
                f"Sync {sync_id} finalized: {len(added)} added, {len(updated)} updated, "
                f"{len(stale)} marked stale. Status: {status_enum.value}."
            ),
            execution_mode=self.settings.execution_mode,
            metadata={
                "added_count": len(added),
                "updated_count": len(updated),
                "stale_count": len(stale),
                "status": status_enum.value,
            },
        )
        return sync_record

    def evaluate_capability_for_workflow(
        self,
        capability: NormalizedCapability,
        workflow: str,
        required_operation: str,
        healthcare_auth_context: Optional[Dict[str, Any]] = None,
    ) -> CapabilityPolicyEvaluation:
        """Evaluate whether a discovered capability can be considered for a healthcare workflow.

        Section 8 Policy Rules:
        - Stale metadata -> BLOCKED_STALE_METADATA
        - Not registered in tenant -> BLOCKED_NOT_REGISTERED
        - Unknown domain / domain mismatch -> BLOCKED_UNKNOWN_CAPABILITY
        - Unsupported operation -> BLOCKED_UNSUPPORTED_OPERATION
        - Unauthorized (or unknown authorization) -> BLOCKED_UNAUTHORIZED
        - Unhealthy or unverified health -> BLOCKED_UNHEALTHY
        - Generic commerce claiming to be pharmacy partner -> BLOCKED_UNKNOWN_CAPABILITY
        - If all pass -> ELIGIBLE_FOR_POLICY_REVIEW (requires HITL approval)
        """
        now = datetime.utcnow()

        # 1. Stale metadata check
        if capability.is_stale:
            return CapabilityPolicyEvaluation(
                capability_id=capability.capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_STALE_METADATA,
                reason=f"Capability '{capability.capability_id}' has stale metadata and was not seen in recent discovery.",
                timestamp=now,
            )

        # 2. Registration check
        if not capability.registered:
            return CapabilityPolicyEvaluation(
                capability_id=capability.capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_NOT_REGISTERED,
                reason=f"Capability '{capability.capability_id}' is not registered in the tenant.",
                timestamp=now,
            )

        # 3. Domain match check
        wf_lower = workflow.lower()
        if "medicine" in wf_lower or "pharmacy" in wf_lower or required_operation in DIRECT_PHARMACY_OPERATIONS:
            if capability.domain not in (HealthcareDomain.MEDICINE_AVAILABILITY, HealthcareDomain.MEDICINE_ORDERING):
                return CapabilityPolicyEvaluation(
                    capability_id=capability.capability_id,
                    workflow=workflow,
                    required_operation=required_operation,
                    decision=CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY,
                    reason=f"Capability '{capability.capability_id}' domain '{capability.domain.value}' does not match workflow '{workflow}'.",
                    timestamp=now,
                )
            # Generic commerce tool exclusion check
            if not capability.is_verified_healthcare_partner:
                return CapabilityPolicyEvaluation(
                    capability_id=capability.capability_id,
                    workflow=workflow,
                    required_operation=required_operation,
                    decision=CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY,
                    reason="Direct Pharmacy API alignment: generic commerce tools cannot be treated as verified direct pharmacy partners.",
                    timestamp=now,
                )

        if "task" in wf_lower and capability.domain != HealthcareDomain.CAREGIVER_TASKS:
            return CapabilityPolicyEvaluation(
                capability_id=capability.capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY,
                reason=f"Capability '{capability.capability_id}' domain '{capability.domain.value}' is not a caregiver task engine.",
                timestamp=now,
            )

        # 4. Supported operation check
        if required_operation not in capability.supported_operations:
            return CapabilityPolicyEvaluation(
                capability_id=capability.capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_UNSUPPORTED_OPERATION,
                reason=f"Capability '{capability.capability_id}' does not support required operation '{required_operation}'. Supported: {capability.supported_operations}",
                timestamp=now,
            )

        # 5. Authorization check (None = unknown, which must block execution!)
        if capability.authorized is not True:
            state_desc = "unauthorized" if capability.authorized is False else "unknown authorization (unverified permissions)"
            return CapabilityPolicyEvaluation(
                capability_id=capability.capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_UNAUTHORIZED,
                reason=f"Capability '{capability.capability_id}' is blocked: {state_desc}. Explicit tenant authorization required.",
                timestamp=now,
            )

        # 6. Health check (None = unknown or False = unhealthy)
        if capability.healthy is not True:
            health_desc = "unhealthy" if capability.healthy is False else "unverified health status"
            return CapabilityPolicyEvaluation(
                capability_id=capability.capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_UNHEALTHY,
                reason=f"Capability '{capability.capability_id}' is blocked: {health_desc}. Valid health check required.",
                timestamp=now,
            )

        # 7. Eligible for policy review
        return CapabilityPolicyEvaluation(
            capability_id=capability.capability_id,
            workflow=workflow,
            required_operation=required_operation,
            decision=CapabilityPolicyDecision.ELIGIBLE_FOR_POLICY_REVIEW,
            reason=(
                f"Capability '{capability.capability_id}' meets operational readiness criteria. "
                "Eligible for policy review only. Does NOT authorize execution; healthcare authorization "
                "engine and HITL approval manager remain authoritative."
            ),
            timestamp=now,
        )
