"""Module 10: Concrete SQLite Repositories.

Implements durable repositories for capabilities, sync history, execution records,
idempotency claims, approval references, and structured audit events using SQLiteStore.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from .base import (
    CapabilityRepository,
    SyncHistoryRepository,
    ExecutionRepository,
    IdempotencyRepository,
    ApprovalRepository,
    AuditRepository,
    AppointmentRepository,
    VoiceRepository,
)
from .sqlite_store import SQLiteStore
from ..models.connector import NormalizedCapability, SyncHistoryRecord
from ..models.approval import ApprovalRecord
from ..models.gateway import ExecutionRequest, ExecutionResult
from ..models.audit import AuditLogEntry
from ..models.appointment import (
    AppointmentRecord,
    AppointmentSlot,
    ClinicInfo,
    DoctorInfo,
)
from ..models.voice import (
    VoiceCallRecord,
)
from ..models.enums import (
    HealthcareDomain,
    GatewayExecutionStatus,
    CapabilityPolicyDecision,
    ApprovalStatus,
    ActionType,
    AuditEventType,
    ExecutionMode,
    DiscoveryStatus,
    VerificationStatus,
    AppointmentStatus,
    VoiceCallStatus,
    VoiceCallDisposition,
)

logger = logging.getLogger(__name__)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _from_iso(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


def _to_json(val: Any) -> Optional[str]:
    if val is None:
        return None
    return json.dumps(val, default=str)


def _from_json(val: Optional[str], default: Any = None) -> Any:
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


# ------------------------------------------------------------------------------
# Capability Repository
# ------------------------------------------------------------------------------
class SQLiteCapabilityRepository(CapabilityRepository):
    """Durable persistence for normalized capabilities in SQLite."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def save(self, capability: NormalizedCapability) -> None:
        """Persist or update a normalized capability, preserving local authorizations."""
        existing = self.get(capability.capability_id)
        preserved_auth = existing.authorized if existing and existing.authorized is not None else capability.authorized

        query = """
        INSERT INTO capabilities (
            capability_id, source_platform, tenant_connector_id, mcp_tool_id,
            display_name, description, domain, category, supported_operations,
            input_schema, output_schema, source_metadata_version, documented,
            registered, authorized, connected, healthy, capable,
            is_verified_healthcare_partner, is_stale, first_discovered_at,
            last_seen_at, raw_metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(capability_id) DO UPDATE SET
            display_name=excluded.display_name,
            description=excluded.description,
            domain=excluded.domain,
            category=excluded.category,
            supported_operations=excluded.supported_operations,
            input_schema=excluded.input_schema,
            output_schema=excluded.output_schema,
            source_metadata_version=excluded.source_metadata_version,
            documented=excluded.documented,
            registered=excluded.registered,
            authorized=excluded.authorized,
            connected=excluded.connected,
            healthy=excluded.healthy,
            capable=excluded.capable,
            is_verified_healthcare_partner=excluded.is_verified_healthcare_partner,
            is_stale=excluded.is_stale,
            last_seen_at=excluded.last_seen_at,
            raw_metadata=excluded.raw_metadata
        """
        now_str = _to_iso(datetime.utcnow())
        first_disc = _to_iso(existing.discovery_timestamp) if existing else _to_iso(capability.discovery_timestamp) or now_str

        params = (
            capability.capability_id,
            capability.source_platform,
            capability.tenant_connector_id,
            capability.mcp_tool_id,
            capability.display_name,
            capability.description,
            capability.domain.value if hasattr(capability.domain, "value") else str(capability.domain),
            capability.category,
            _to_json(capability.supported_operations),
            _to_json(capability.input_schema),
            _to_json(capability.output_schema),
            capability.source_metadata_version,
            1 if capability.documented else 0,
            1 if capability.registered else 0,
            1 if preserved_auth is True else (0 if preserved_auth is False else None),
            1 if capability.connected is True else (0 if capability.connected is False else None),
            1 if capability.healthy is True else (0 if capability.healthy is False else None),
            1 if capability.capable is True else (0 if capability.capable is False else None),
            1 if capability.is_verified_healthcare_partner else 0,
            1 if capability.is_stale else 0,
            first_disc,
            _to_iso(capability.last_seen_at) or now_str,
            _to_json(capability.raw_metadata),
        )
        self.store.execute(query, params)

    def save_all(self, capabilities: List[NormalizedCapability]) -> None:
        """Persist batch of capabilities inside a single transaction."""
        with self.store.transaction() as cursor:
            for cap in capabilities:
                # Query existing to preserve authorization
                cursor.execute("SELECT authorized, first_discovered_at FROM capabilities WHERE capability_id = ?", (cap.capability_id,))
                row = cursor.fetchone()
                existing_auth = None
                first_disc = _to_iso(cap.discovery_timestamp) or _to_iso(datetime.utcnow())
                if row:
                    raw_auth = row["authorized"]
                    existing_auth = True if raw_auth == 1 else (False if raw_auth == 0 else None)
                    if row["first_discovered_at"]:
                        first_disc = row["first_discovered_at"]

                preserved_auth = existing_auth if existing_auth is not None else cap.authorized

                query = """
                INSERT INTO capabilities (
                    capability_id, source_platform, tenant_connector_id, mcp_tool_id,
                    display_name, description, domain, category, supported_operations,
                    input_schema, output_schema, source_metadata_version, documented,
                    registered, authorized, connected, healthy, capable,
                    is_verified_healthcare_partner, is_stale, first_discovered_at,
                    last_seen_at, raw_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    description=excluded.description,
                    domain=excluded.domain,
                    category=excluded.category,
                    supported_operations=excluded.supported_operations,
                    input_schema=excluded.input_schema,
                    output_schema=excluded.output_schema,
                    source_metadata_version=excluded.source_metadata_version,
                    documented=excluded.documented,
                    registered=excluded.registered,
                    authorized=excluded.authorized,
                    connected=excluded.connected,
                    healthy=excluded.healthy,
                    capable=excluded.capable,
                    is_verified_healthcare_partner=excluded.is_verified_healthcare_partner,
                    is_stale=excluded.is_stale,
                    last_seen_at=excluded.last_seen_at,
                    raw_metadata=excluded.raw_metadata
                """
                params = (
                    cap.capability_id,
                    cap.source_platform,
                    cap.tenant_connector_id,
                    cap.mcp_tool_id,
                    cap.display_name,
                    cap.description,
                    cap.domain.value if hasattr(cap.domain, "value") else str(cap.domain),
                    cap.category,
                    _to_json(cap.supported_operations),
                    _to_json(cap.input_schema),
                    _to_json(cap.output_schema),
                    cap.source_metadata_version,
                    1 if cap.documented else 0,
                    1 if cap.registered else 0,
                    1 if preserved_auth is True else (0 if preserved_auth is False else None),
                    1 if cap.connected is True else (0 if cap.connected is False else None),
                    1 if cap.healthy is True else (0 if cap.healthy is False else None),
                    1 if cap.capable is True else (0 if cap.capable is False else None),
                    1 if cap.is_verified_healthcare_partner else 0,
                    1 if cap.is_stale else 0,
                    first_disc,
                    _to_iso(cap.last_seen_at) or _to_iso(datetime.utcnow()),
                    _to_json(cap.raw_metadata),
                )
                cursor.execute(query, params)

    def _row_to_capability(self, row: Dict[str, Any]) -> NormalizedCapability:
        auth_val = True if row["authorized"] == 1 else (False if row["authorized"] == 0 else None)
        conn_val = True if row["connected"] == 1 else (False if row["connected"] == 0 else None)
        hlth_val = True if row["healthy"] == 1 else (False if row["healthy"] == 0 else None)
        cap_val = True if row["capable"] == 1 else (False if row["capable"] == 0 else None)

        domain_str = row["domain"]
        try:
            domain = HealthcareDomain(domain_str)
        except Exception:
            domain = HealthcareDomain.UNKNOWN

        return NormalizedCapability(
            capability_id=row["capability_id"],
            source_platform=row["source_platform"],
            tenant_connector_id=row["tenant_connector_id"],
            mcp_tool_id=row["mcp_tool_id"],
            display_name=row["display_name"],
            description=row["description"] or "",
            domain=domain,
            category=row["category"],
            supported_operations=_from_json(row["supported_operations"], []),
            input_schema=_from_json(row["input_schema"]),
            output_schema=_from_json(row["output_schema"]),
            source_metadata_version=row["source_metadata_version"],
            documented=bool(row["documented"]),
            registered=bool(row["registered"]),
            authorized=auth_val,
            connected=conn_val,
            healthy=hlth_val,
            capable=cap_val,
            is_verified_healthcare_partner=bool(row["is_verified_healthcare_partner"]),
            is_stale=bool(row["is_stale"]),
            discovery_timestamp=_from_iso(row["first_discovered_at"]) or datetime.utcnow(),
            last_seen_at=_from_iso(row["last_seen_at"]) or datetime.utcnow(),
            raw_metadata=_from_json(row["raw_metadata"], {}),
        )

    def get(self, capability_id: str) -> Optional[NormalizedCapability]:
        row = self.store.fetchone("SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,))
        if not row:
            return None
        return self._row_to_capability(row)

    def list_all(self, include_stale: bool = True) -> List[NormalizedCapability]:
        if include_stale:
            rows = self.store.fetchall("SELECT * FROM capabilities ORDER BY capability_id ASC")
        else:
            rows = self.store.fetchall("SELECT * FROM capabilities WHERE is_stale = 0 ORDER BY capability_id ASC")
        return [self._row_to_capability(r) for r in rows]

    def mark_stale(self, capability_id: str) -> None:
        self.store.execute("UPDATE capabilities SET is_stale = 1 WHERE capability_id = ?", (capability_id,))

    def count(self) -> int:
        row = self.store.fetchone("SELECT COUNT(*) as cnt FROM capabilities")
        return int(row["cnt"]) if row else 0


# ------------------------------------------------------------------------------
# Synchronization History Repository
# ------------------------------------------------------------------------------
class SQLiteSyncHistoryRepository(SyncHistoryRepository):
    """Durable persistence for synchronization runs."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def record_sync(self, sync_record: SyncHistoryRecord) -> None:
        query = """
        INSERT INTO sync_history (
            sync_id, started_at, completed_at, discovery_status,
            connector_discovery_result, mcp_discovery_result,
            added_capabilities, updated_capabilities, stale_capabilities,
            failure_category, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        stat = getattr(sync_record, "status", getattr(sync_record, "discovery_status", DiscoveryStatus.SUCCESS))
        disc_val = stat.value if hasattr(stat, "value") else str(stat)
        params = (
            sync_record.sync_id,
            _to_iso(sync_record.started_at),
            _to_iso(sync_record.completed_at),
            disc_val,
            _to_json(getattr(sync_record, "connector_discovery_result", {})),
            _to_json(getattr(sync_record, "mcp_discovery_result", {})),
            _to_json(sync_record.added_capabilities),
            _to_json(sync_record.updated_capabilities),
            _to_json(sync_record.stale_capabilities),
            getattr(sync_record, "failure_category", None),
            (sync_record.sanitized_errors[0] if sync_record.sanitized_errors else None) if hasattr(sync_record, "sanitized_errors") else None,
        )
        self.store.execute(query, params)

    def _row_to_record(self, row: Dict[str, Any]) -> SyncHistoryRecord:
        try:
            status = DiscoveryStatus(row["discovery_status"])
        except Exception:
            status = DiscoveryStatus.DISCOVERY_FAILED

        return SyncHistoryRecord(
            sync_id=row["sync_id"],
            started_at=_from_iso(row["started_at"]) or datetime.utcnow(),
            completed_at=_from_iso(row["completed_at"]) or datetime.utcnow(),
            discovery_source="agenticorg_tenant",
            status=status,
            added_capabilities=_from_json(row["added_capabilities"], []),
            updated_capabilities=_from_json(row["updated_capabilities"], []),
            stale_capabilities=_from_json(row["stale_capabilities"], []),
            sanitized_errors=[row["error_message"]] if row.get("error_message") else [],
        )

    def get_latest_sync(self) -> Optional[SyncHistoryRecord]:
        row = self.store.fetchone("SELECT * FROM sync_history ORDER BY started_at DESC LIMIT 1")
        if not row:
            return None
        return self._row_to_record(row)

    def list_syncs(self, limit: int = 50) -> List[SyncHistoryRecord]:
        rows = self.store.fetchall("SELECT * FROM sync_history ORDER BY started_at DESC LIMIT ?", (limit,))
        return [self._row_to_record(r) for r in rows]


# ------------------------------------------------------------------------------
# Execution Repository
# ------------------------------------------------------------------------------
class SQLiteExecutionRepository(ExecutionRepository):
    """Durable persistence for gateway execution records and crash recovery."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def save_execution(self, execution: ExecutionResult, request: Optional[ExecutionRequest] = None) -> None:
        query = """
        INSERT INTO execution_records (
            execution_id, request_id, workflow_id, capability_id, operation,
            user_id, patient_id, execution_mode, status, policy_decision,
            approval_id, idempotency_key, handler_invoked, is_simulated,
            error_category, error_message, output, verification_status,
            created_at, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(execution_id) DO UPDATE SET
            status=excluded.status,
            policy_decision=excluded.policy_decision,
            error_category=excluded.error_category,
            error_message=excluded.error_message,
            output=excluded.output,
            verification_status=excluded.verification_status,
            handler_invoked=excluded.handler_invoked,
            is_simulated=excluded.is_simulated,
            completed_at=excluded.completed_at
        """
        now_str = _to_iso(execution.timestamp or datetime.utcnow())
        workflow_id = request.workflow_id if request else None
        user_id = request.requesting_user_id if request else None
        patient_id = request.patient_id if request else None
        exec_mode = (
            request.execution_mode.value
            if request and hasattr(request.execution_mode, "value")
            else "SIMULATION"
        )
        approval_id = request.approval_id if request else None
        idempotency_key = request.idempotency_key if request else None

        params = (
            execution.execution_id,
            execution.request_id,
            workflow_id,
            execution.capability_id,
            execution.operation,
            user_id,
            patient_id,
            exec_mode,
            execution.status.value if hasattr(execution.status, "value") else str(execution.status),
            execution.policy_decision.value if hasattr(execution.policy_decision, "value") else str(execution.policy_decision),
            approval_id,
            idempotency_key,
            1 if execution.handler_invoked else 0,
            1 if execution.is_simulated else 0,
            execution.error_category,
            execution.error_message,
            _to_json(execution.output),
            execution.verification_status.value if hasattr(execution.verification_status, "value") else str(execution.verification_status or "not_applicable"),
            now_str,
            now_str,
            now_str,
        )
        self.store.execute(query, params)

    def _row_to_result(self, row: Dict[str, Any]) -> ExecutionResult:
        try:
            status = GatewayExecutionStatus(row["status"])
        except Exception:
            status = GatewayExecutionStatus.FAILED

        try:
            policy_dec = CapabilityPolicyDecision(row["policy_decision"])
        except Exception:
            policy_dec = CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY

        verif_str = row["verification_status"] or "not_applicable"
        try:
            verif_status = VerificationStatus(verif_str)
        except Exception:
            verif_status = VerificationStatus.NOT_APPLICABLE

        return ExecutionResult(
            execution_id=row["execution_id"],
            request_id=row["request_id"],
            capability_id=row["capability_id"],
            operation=row["operation"],
            status=status,
            policy_decision=policy_dec,
            handler_invoked=bool(row["handler_invoked"]),
            is_simulated=bool(row["is_simulated"]),
            output=_from_json(row["output"]),
            error_category=row["error_category"],
            error_message=row["error_message"],
            verification_status=verif_status,
            timestamp=_from_iso(row["created_at"]) or datetime.utcnow(),
        )

    def get_execution(self, execution_id: str) -> Optional[ExecutionResult]:
        row = self.store.fetchone("SELECT * FROM execution_records WHERE execution_id = ?", (execution_id,))
        if not row:
            return None
        return self._row_to_result(row)

    def get_by_request_id(self, request_id: str) -> Optional[ExecutionResult]:
        row = self.store.fetchone(
            "SELECT * FROM execution_records WHERE request_id = ? ORDER BY created_at DESC LIMIT 1",
            (request_id,),
        )
        if not row:
            return None
        return self._row_to_result(row)

    def list_executions(self, limit: int = 50, user_id: Optional[str] = None) -> List[ExecutionResult]:
        if user_id:
            rows = self.store.fetchall(
                "SELECT * FROM execution_records WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            rows = self.store.fetchall(
                "SELECT * FROM execution_records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_result(r) for r in rows]

    def update_status(
        self,
        execution_id: str,
        status: GatewayExecutionStatus,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now_str = _to_iso(datetime.utcnow())
        query = """
        UPDATE execution_records
        SET status = ?, error_category = COALESCE(?, error_category),
            error_message = COALESCE(?, error_message), completed_at = ?
        WHERE execution_id = ?
        """
        self.store.execute(query, (status.value, error_category, error_message, now_str, execution_id))

    def recover_interrupted_executions(self) -> List[str]:
        """Crash recovery: Mark interrupted/unfinalized executions as UNKNOWN_OUTCOME.
        
        Never automatically resubmit interrupted executions.
        Preserves their original idempotency association.
        """
        now_str = _to_iso(datetime.utcnow())
        # Intermediate/dispatched states that were interrupted before finalization
        query = """
        SELECT execution_id, idempotency_key FROM execution_records
        WHERE status IN ('CLAIMED', 'DISPATCHING', 'SUBMITTED', 'READY')
        """
        rows = self.store.fetchall(query)
        recovered_ids: List[str] = []

        if not rows:
            return recovered_ids

        with self.store.transaction() as cursor:
            for row in rows:
                eid = row["execution_id"]
                cursor.execute(
                    """
                    UPDATE execution_records
                    SET status = 'UNKNOWN_OUTCOME',
                        verification_status = 'pending_verification',
                        error_category = 'INTERRUPTED_EXECUTION_RECOVERED',
                        error_message = 'Process terminated or restarted while execution was in-flight. Marked as UNKNOWN_OUTCOME to prevent duplicate execution.',
                        completed_at = ?
                    WHERE execution_id = ?
                    """,
                    (now_str, eid),
                )
                if row["idempotency_key"]:
                    cursor.execute(
                        """
                        UPDATE idempotency_records
                        SET status = 'UNKNOWN_OUTCOME', updated_at = ?
                        WHERE idempotency_key = ?
                        """,
                        (now_str, row["idempotency_key"]),
                    )
                recovered_ids.append(eid)

        logger.warning(
            "Crash Recovery: Recovered %d interrupted executions into UNKNOWN_OUTCOME state: %s",
            len(recovered_ids),
            recovered_ids,
        )
        return recovered_ids


# ------------------------------------------------------------------------------
# Idempotency Repository
# ------------------------------------------------------------------------------
class SQLiteIdempotencyRepository(IdempotencyRepository):
    """Enforces atomic duplicate prevention and concurrent claim protection in SQLite."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def claim_key(
        self,
        idempotency_key: str,
        execution_id: str,
        user_id: Optional[str],
        operation: str,
        request_fingerprint: str,
    ) -> bool:
        """Atomically claim an idempotency key before dispatch.
        
        Returns:
            True if key was claimed (first execution).
            False if key already exists (duplicate request).
        """
        now_str = _to_iso(datetime.utcnow())
        query = """
        INSERT INTO idempotency_records (
            idempotency_key, execution_id, user_id, operation,
            request_fingerprint, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'CLAIMED', ?, ?)
        """
        params = (
            idempotency_key,
            execution_id,
            user_id,
            operation,
            request_fingerprint,
            now_str,
            now_str,
        )
        try:
            self.store.execute(query, params)
            return True
        except sqlite3.IntegrityError as e:
            if "unique" in str(e).lower():
                # Primary key uniqueness constraint violation -> already claimed
                logger.info("Idempotency key '%s' collision: already claimed.", idempotency_key)
                return False
            # Foreign key or other constraint violation
            logger.error("Integrity error claiming idempotency key: %s", str(e))
            raise

    def get_record(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        return self.store.fetchone(
            "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
            (idempotency_key,),
        )

    def update_status(self, idempotency_key: str, status: str) -> None:
        now_str = _to_iso(datetime.utcnow())
        self.store.execute(
            "UPDATE idempotency_records SET status = ?, updated_at = ? WHERE idempotency_key = ?",
            (status, now_str, idempotency_key),
        )


# ------------------------------------------------------------------------------
# Approval Repository
# ------------------------------------------------------------------------------
class SQLiteApprovalRepository(ApprovalRepository):
    """Durable persistence for HITL approval records."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def save_approval(self, approval: ApprovalRecord) -> None:
        query = """
        INSERT INTO approvals (
            approval_id, request_id, user_identity, patient_id,
            action_being_approved, parameter_hash, parameters,
            approval_status, granted_by, granted_at, rejection_reason,
            expiration, is_simulation, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(approval_id) DO UPDATE SET
            approval_status=excluded.approval_status,
            granted_by=excluded.granted_by,
            granted_at=excluded.granted_at,
            rejection_reason=excluded.rejection_reason
        """
        act_val = (
            approval.action_being_approved.value
            if hasattr(approval.action_being_approved, "value")
            else str(approval.action_being_approved)
        )
        stat_val = (
            approval.approval_status.value
            if hasattr(approval.approval_status, "value")
            else str(approval.approval_status)
        )
        params_dict = getattr(approval, "relevant_parameters", getattr(approval, "parameters", {}))
        patient_id = getattr(approval, "patient_id", None)
        if not patient_id and isinstance(params_dict, dict):
            patient_id = params_dict.get("patient_id")
        created_time = getattr(approval, "timestamp", getattr(approval, "created_at", None))
        now_str = _to_iso(created_time) if created_time else _to_iso(datetime.utcnow())
        params = (
            approval.approval_id,
            approval.request_id,
            approval.user_identity,
            patient_id,
            act_val,
            approval.parameter_hash,
            _to_json(params_dict),
            stat_val,
            approval.granted_by,
            _to_iso(approval.granted_at),
            approval.rejection_reason,
            _to_iso(approval.expiration),
            1 if approval.is_simulation else 0,
            now_str,
        )
        self.store.execute(query, params)

    def _row_to_approval(self, row: Dict[str, Any]) -> ApprovalRecord:
        try:
            act_type = ActionType(row["action_being_approved"])
        except Exception:
            act_type = ActionType.GENERAL_OPERATION

        try:
            app_status = ApprovalStatus(row["approval_status"])
        except Exception:
            app_status = ApprovalStatus.PENDING

        raw_params = _from_json(row["parameters"], {})
        return ApprovalRecord(
            approval_id=row["approval_id"],
            request_id=row["request_id"],
            user_identity=row["user_identity"],
            action_being_approved=act_type,
            parameter_hash=row["parameter_hash"],
            relevant_parameters=raw_params,
            approval_status=app_status,
            granted_by=row["granted_by"],
            granted_at=_from_iso(row["granted_at"]),
            rejection_reason=row["rejection_reason"],
            expiration=_from_iso(row["expiration"]) or datetime.utcnow(),
            is_simulation=bool(row["is_simulation"]),
            timestamp=_from_iso(row["created_at"]) or datetime.utcnow(),
        )

    def get_approval(self, approval_id: str) -> Optional[ApprovalRecord]:
        row = self.store.fetchone("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
        if not row:
            return None
        return self._row_to_approval(row)

    def update_status(
        self,
        approval_id: str,
        status: ApprovalStatus,
        granted_by: Optional[str] = None,
        rejection_reason: Optional[str] = None,
    ) -> None:
        now_str = _to_iso(datetime.utcnow()) if status == ApprovalStatus.GRANTED else None
        query = """
        UPDATE approvals
        SET approval_status = ?, granted_by = COALESCE(?, granted_by),
            granted_at = COALESCE(?, granted_at),
            rejection_reason = COALESCE(?, rejection_reason)
        WHERE approval_id = ?
        """
        self.store.execute(query, (status.value, granted_by, now_str, rejection_reason, approval_id))

    def list_pending(self, user_identity: Optional[str] = None) -> List[ApprovalRecord]:
        if user_identity:
            rows = self.store.fetchall(
                "SELECT * FROM approvals WHERE approval_status = 'PENDING' AND user_identity = ? ORDER BY created_at DESC",
                (user_identity,),
            )
        else:
            rows = self.store.fetchall(
                "SELECT * FROM approvals WHERE approval_status = 'PENDING' ORDER BY created_at DESC"
            )
        return [self._row_to_approval(r) for r in rows]


# ------------------------------------------------------------------------------
# Audit Repository
# ------------------------------------------------------------------------------
class SQLiteAuditRepository(AuditRepository):
    """Durable persistence for structured audit events."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def record_event(self, entry: AuditLogEntry) -> None:
        query = """
        INSERT OR IGNORE INTO audit_events (
            event_id, event_type, timestamp, status, details,
            request_id, patient_id, user_id, operation_type,
            execution_mode, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        mode_val = (
            entry.execution_mode.value
            if hasattr(entry.execution_mode, "value")
            else str(entry.execution_mode)
        )
        type_val = (
            entry.event_type.value
            if hasattr(entry.event_type, "value")
            else str(entry.event_type)
        )
        params = (
            entry.audit_id,
            type_val,
            _to_iso(entry.timestamp),
            entry.status,
            entry.details,
            entry.request_id,
            entry.patient_id,
            entry.user_id,
            entry.operation_type,
            mode_val,
            _to_json(entry.metadata),
        )
        self.store.execute(query, params)

    def _row_to_entry(self, row: Dict[str, Any]) -> AuditLogEntry:
        try:
            ev_type = AuditEventType(row["event_type"])
        except Exception:
            ev_type = AuditEventType.GENERAL_AUDIT

        try:
            mode = ExecutionMode(row["execution_mode"])
        except Exception:
            mode = ExecutionMode.SIMULATION

        return AuditLogEntry(
            audit_id=row["event_id"],
            event_type=ev_type,
            timestamp=_from_iso(row["timestamp"]) or datetime.utcnow(),
            status=row["status"],
            details=row["details"],
            request_id=row["request_id"],
            patient_id=row["patient_id"],
            user_id=row["user_id"],
            operation_type=row["operation_type"],
            execution_mode=mode,
            metadata=_from_json(row["metadata"], {}),
        )

    def list_events(
        self,
        limit: int = 100,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[AuditLogEntry]:
        if request_id and user_id:
            rows = self.store.fetchall(
                "SELECT * FROM audit_events WHERE request_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (request_id, user_id, limit),
            )
        elif request_id:
            rows = self.store.fetchall(
                "SELECT * FROM audit_events WHERE request_id = ? ORDER BY timestamp DESC LIMIT ?",
                (request_id, limit),
            )
        elif user_id:
            rows = self.store.fetchall(
                "SELECT * FROM audit_events WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            rows = self.store.fetchall(
                "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_entry(r) for r in rows]

    def import_from_jsonl(self, jsonl_path: str) -> int:
        """Safely import existing JSONL audit entries without duplicates."""
        import os
        if not os.path.exists(jsonl_path):
            logger.info("JSONL audit file '%s' does not exist; skipping import.", jsonl_path)
            return 0

        imported_count = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        with self.store.transaction() as cursor:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = AuditLogEntry(**data)
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO audit_events (
                            event_id, event_type, timestamp, status, details,
                            request_id, patient_id, user_id, operation_type,
                            execution_mode, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.audit_id,
                            entry.event_type.value if hasattr(entry.event_type, "value") else str(entry.event_type),
                            _to_iso(entry.timestamp),
                            entry.status,
                            entry.details,
                            entry.request_id,
                            entry.patient_id,
                            entry.user_id,
                            entry.operation_type,
                            entry.execution_mode.value if hasattr(entry.execution_mode, "value") else str(entry.execution_mode),
                            _to_json(entry.metadata),
                        ),
                    )
                    if cursor.rowcount > 0:
                        imported_count += 1
                except Exception as e:
                    logger.warning("Could not parse audit log line during import: %s | error: %s", line[:50], str(e))

        logger.info("Imported %d new audit entries from '%s'.", imported_count, jsonl_path)
        return imported_count


# ------------------------------------------------------------------------------
# Phase 14: Appointment Repository
# ------------------------------------------------------------------------------
class SQLiteAppointmentRepository(AppointmentRepository):
    """Durable SQLite persistence for appointment records."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def _row_to_record(self, row: Dict[str, Any]) -> AppointmentRecord:
        clinic_dict = _from_json(row["clinic_json"], {})
        doctor_dict = _from_json(row.get("doctor_json"))
        available_slots_data = _from_json(row.get("available_slots"), [])
        approved_slot_data = _from_json(row.get("approved_slot"))
        metadata = _from_json(row.get("metadata"), {})

        return AppointmentRecord(
            appointment_id=row["appointment_id"],
            request_id=row["request_id"],
            patient_id=row["patient_id"],
            requesting_user_id=row["requesting_user_id"],
            clinic=ClinicInfo(**clinic_dict),
            doctor=DoctorInfo(**doctor_dict) if doctor_dict else None,
            preferred_date=row["preferred_date"],
            preferred_time=row.get("preferred_time"),
            status=AppointmentStatus(row["status"]),
            available_slots=[AppointmentSlot(**s) for s in available_slots_data],
            approved_slot=AppointmentSlot(**approved_slot_data) if approved_slot_data else None,
            clinic_booking_reference=row.get("clinic_booking_reference"),
            failure_reason=row.get("failure_reason"),
            uncertainty_reason=row.get("uncertainty_reason"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            idempotency_key=row.get("idempotency_key"),
            correlation_id=row.get("correlation_id"),
            metadata=metadata,
        )

    def save(self, record: AppointmentRecord) -> None:
        with self.store.transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO appointments (
                    appointment_id, request_id, patient_id, requesting_user_id,
                    clinic_json, doctor_json, preferred_date, preferred_time,
                    status, available_slots, approved_slot, clinic_booking_reference,
                    failure_reason, uncertainty_reason, created_at, updated_at,
                    idempotency_key, correlation_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.appointment_id,
                    record.request_id,
                    record.patient_id,
                    record.requesting_user_id,
                    _to_json(record.clinic.model_dump() if hasattr(record.clinic, "model_dump") else record.clinic.dict()),
                    _to_json(record.doctor.model_dump() if hasattr(record.doctor, "model_dump") else record.doctor.dict()) if record.doctor else None,
                    record.preferred_date,
                    record.preferred_time,
                    record.status.value if hasattr(record.status, "value") else str(record.status),
                    _to_json([s.model_dump() if hasattr(s, "model_dump") else s.dict() for s in record.available_slots]),
                    _to_json(record.approved_slot.model_dump() if hasattr(record.approved_slot, "model_dump") else record.approved_slot.dict()) if record.approved_slot else None,
                    record.clinic_booking_reference,
                    record.failure_reason,
                    record.uncertainty_reason,
                    record.created_at,
                    record.updated_at,
                    record.idempotency_key,
                    record.correlation_id,
                    _to_json(record.metadata),
                ),
            )

    def get(self, appointment_id: str) -> Optional[AppointmentRecord]:
        row = self.store.fetchone(
            "SELECT * FROM appointments WHERE appointment_id = ?",
            (appointment_id,),
        )
        return self._row_to_record(row) if row else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[AppointmentRecord]:
        row = self.store.fetchone(
            "SELECT * FROM appointments WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return self._row_to_record(row) if row else None

    def list_by_patient(self, patient_id: str) -> List[AppointmentRecord]:
        rows = self.store.fetchall(
            "SELECT * FROM appointments WHERE patient_id = ? ORDER BY created_at DESC",
            (patient_id,),
        )
        return [self._row_to_record(r) for r in rows]

    def update_status(
        self,
        appointment_id: str,
        status: AppointmentStatus,
        failure_reason: Optional[str] = None,
        clinic_booking_reference: Optional[str] = None,
        approved_slot: Optional[AppointmentSlot] = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        status_val = status.value if hasattr(status, "value") else str(status)
        approved_json = _to_json(approved_slot.model_dump() if hasattr(approved_slot, "model_dump") else approved_slot.dict()) if approved_slot else None

        with self.store.transaction() as cursor:
            cursor.execute(
                """
                UPDATE appointments
                SET status = ?,
                    failure_reason = COALESCE(?, failure_reason),
                    clinic_booking_reference = COALESCE(?, clinic_booking_reference),
                    approved_slot = CASE WHEN ? IS NOT NULL THEN ? ELSE approved_slot END,
                    updated_at = ?
                WHERE appointment_id = ?
                """,
                (
                    status_val,
                    failure_reason,
                    clinic_booking_reference,
                    approved_json,
                    approved_json,
                    now,
                    appointment_id,
                ),
            )


# ------------------------------------------------------------------------------
# Phase 14: Voice Repository
# ------------------------------------------------------------------------------
class SQLiteVoiceRepository(VoiceRepository):
    """Durable SQLite persistence for voice calls and external webhook idempotency."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def _row_to_call(self, row: Dict[str, Any]) -> VoiceCallRecord:
        available_slots_data = _from_json(row.get("available_slots"), [])
        selected_slot_data = _from_json(row.get("selected_slot"))
        metadata = _from_json(row.get("metadata"), {})

        return VoiceCallRecord(
            call_id=row["call_id"],
            external_call_id=row["external_call_id"],
            appointment_id=row["appointment_id"],
            clinic_id=row.get("clinic_id"),
            clinic_name=row.get("clinic_name"),
            status=VoiceCallStatus(row["status"]),
            disposition=VoiceCallDisposition(row["disposition"]),
            available_slots=[AppointmentSlot(**s) for s in available_slots_data],
            selected_slot=AppointmentSlot(**selected_slot_data) if selected_slot_data else None,
            booking_outcome=row.get("booking_outcome"),
            booking_reference=row.get("booking_reference"),
            failure_reason=row.get("failure_reason"),
            callback_required=bool(row.get("callback_required", 0)),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            idempotency_key=row["idempotency_key"],
            metadata=metadata,
        )

    def save_call(self, call: VoiceCallRecord) -> None:
        with self.store.transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO voice_call_records (
                    call_id, external_call_id, appointment_id, clinic_id, clinic_name,
                    status, disposition, available_slots, selected_slot, booking_outcome,
                    booking_reference, failure_reason, callback_required, created_at,
                    updated_at, idempotency_key, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call.call_id,
                    call.external_call_id,
                    call.appointment_id,
                    call.clinic_id,
                    call.clinic_name,
                    call.status.value if hasattr(call.status, "value") else str(call.status),
                    call.disposition.value if hasattr(call.disposition, "value") else str(call.disposition),
                    _to_json([s.model_dump() if hasattr(s, "model_dump") else s.dict() for s in call.available_slots]),
                    _to_json(call.selected_slot.model_dump() if hasattr(call.selected_slot, "model_dump") else call.selected_slot.dict()) if call.selected_slot else None,
                    call.booking_outcome,
                    call.booking_reference,
                    call.failure_reason,
                    1 if call.callback_required else 0,
                    call.created_at,
                    call.updated_at,
                    call.idempotency_key,
                    _to_json(call.metadata),
                ),
            )

    def get_call(self, call_id: str) -> Optional[VoiceCallRecord]:
        row = self.store.fetchone(
            "SELECT * FROM voice_call_records WHERE call_id = ?",
            (call_id,),
        )
        return self._row_to_call(row) if row else None

    def get_by_external_id(self, external_call_id: str) -> Optional[VoiceCallRecord]:
        row = self.store.fetchone(
            "SELECT * FROM voice_call_records WHERE external_call_id = ?",
            (external_call_id,),
        )
        return self._row_to_call(row) if row else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[VoiceCallRecord]:
        row = self.store.fetchone(
            "SELECT * FROM voice_call_records WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return self._row_to_call(row) if row else None

    def list_by_appointment(self, appointment_id: str) -> List[VoiceCallRecord]:
        rows = self.store.fetchall(
            "SELECT * FROM voice_call_records WHERE appointment_id = ? ORDER BY created_at DESC",
            (appointment_id,),
        )
        return [self._row_to_call(r) for r in rows]

    def record_external_event(
        self,
        event_id: str,
        event_source: str,
        event_type: str,
        idempotency_key: str,
        payload: str,
        status: str = "PROCESSED",
    ) -> bool:
        """Atomically record an incoming external event. Returns False if already processed."""
        now = datetime.utcnow().isoformat()
        try:
            with self.store.transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO external_events (
                        event_id, event_source, event_type, idempotency_key, payload, processed_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, event_source, event_type, idempotency_key, payload, now, status),
                )
            return True
        except sqlite3.IntegrityError:
            logger.warning("Duplicate external event detected with idempotency_key='%s'", idempotency_key)
            return False

    def get_external_event(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        return self.store.fetchone(
            "SELECT * FROM external_events WHERE idempotency_key = ?",
            (idempotency_key,),
        )
