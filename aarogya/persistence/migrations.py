"""Module 10: Database Schema Migrations.

Versioned schema initialization and migrations for Aarogya's durable persistence layer.
Enforces parameterized schema creation, indexes, foreign keys, and version tracking.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2

MIGRATION_V1_DDL = """
-- Version tracking table
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL,
    description TEXT NOT NULL
);

-- Connector & MCP capabilities catalog
CREATE TABLE IF NOT EXISTS capabilities (
    capability_id TEXT PRIMARY KEY,
    source_platform TEXT NOT NULL,
    tenant_connector_id TEXT,
    mcp_tool_id TEXT,
    display_name TEXT NOT NULL,
    description TEXT,
    domain TEXT NOT NULL,
    category TEXT,
    supported_operations TEXT NOT NULL,
    input_schema TEXT,
    output_schema TEXT,
    source_metadata_version TEXT,
    documented INTEGER NOT NULL DEFAULT 1,
    registered INTEGER NOT NULL DEFAULT 0,
    authorized INTEGER,
    connected INTEGER,
    healthy INTEGER,
    capable INTEGER,
    is_verified_healthcare_partner INTEGER NOT NULL DEFAULT 0,
    is_stale INTEGER NOT NULL DEFAULT 0,
    first_discovered_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    raw_metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_capabilities_domain ON capabilities(domain);
CREATE INDEX IF NOT EXISTS idx_capabilities_stale ON capabilities(is_stale);

-- Capability synchronization history
CREATE TABLE IF NOT EXISTS sync_history (
    sync_id TEXT PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP NOT NULL,
    discovery_status TEXT NOT NULL,
    connector_discovery_result TEXT,
    mcp_discovery_result TEXT,
    added_capabilities TEXT NOT NULL,
    updated_capabilities TEXT NOT NULL,
    stale_capabilities TEXT NOT NULL,
    failure_category TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_history_started ON sync_history(started_at);

-- Execution records
CREATE TABLE IF NOT EXISTS execution_records (
    execution_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    workflow_id TEXT,
    capability_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    user_id TEXT,
    patient_id TEXT,
    execution_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    policy_decision TEXT NOT NULL,
    approval_id TEXT,
    idempotency_key TEXT,
    handler_invoked INTEGER NOT NULL DEFAULT 0,
    is_simulated INTEGER NOT NULL DEFAULT 0,
    error_category TEXT,
    error_message TEXT,
    output TEXT,
    verification_status TEXT,
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_executions_request_id ON execution_records(request_id);
CREATE INDEX IF NOT EXISTS idx_executions_workflow_id ON execution_records(workflow_id);
CREATE INDEX IF NOT EXISTS idx_executions_capability_id ON execution_records(capability_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON execution_records(status);
CREATE INDEX IF NOT EXISTS idx_executions_user_id ON execution_records(user_id);

-- Durable Idempotency records
CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    user_id TEXT,
    operation TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY(execution_id) REFERENCES execution_records(execution_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_idempotency_execution_id ON idempotency_records(execution_id);
CREATE INDEX IF NOT EXISTS idx_idempotency_user_op ON idempotency_records(user_id, operation);

-- Human-in-the-Loop approvals
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    user_identity TEXT NOT NULL,
    patient_id TEXT,
    action_being_approved TEXT NOT NULL,
    parameter_hash TEXT NOT NULL,
    parameters TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    granted_by TEXT,
    granted_at TIMESTAMP,
    rejection_reason TEXT,
    expiration TIMESTAMP NOT NULL,
    is_simulation INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approvals_user_status ON approvals(user_identity, approval_status);
CREATE INDEX IF NOT EXISTS idx_approvals_request_id ON approvals(request_id);

-- Structured audit events
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    status TEXT NOT NULL,
    details TEXT NOT NULL,
    request_id TEXT,
    patient_id TEXT,
    user_id TEXT,
    operation_type TEXT,
    execution_mode TEXT NOT NULL,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_request_id ON audit_events(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events(event_type);
"""

MIGRATION_V2_DDL = """
-- Phase 14: Appointments table
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    requesting_user_id TEXT NOT NULL,
    clinic_json TEXT NOT NULL,
    doctor_json TEXT,
    preferred_date TEXT NOT NULL,
    preferred_time TEXT,
    status TEXT NOT NULL,
    available_slots TEXT NOT NULL,
    approved_slot TEXT,
    clinic_booking_reference TEXT,
    failure_reason TEXT,
    uncertainty_reason TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    idempotency_key TEXT,
    correlation_id TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_requesting_user_id ON appointments(requesting_user_id);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_appointments_idempotency_key ON appointments(idempotency_key);

-- Phase 14: Voice call records
CREATE TABLE IF NOT EXISTS voice_call_records (
    call_id TEXT PRIMARY KEY,
    external_call_id TEXT NOT NULL,
    appointment_id TEXT NOT NULL,
    clinic_id TEXT,
    clinic_name TEXT,
    status TEXT NOT NULL,
    disposition TEXT NOT NULL,
    available_slots TEXT NOT NULL,
    selected_slot TEXT,
    booking_outcome TEXT,
    booking_reference TEXT,
    failure_reason TEXT,
    callback_required INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    idempotency_key TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY(appointment_id) REFERENCES appointments(appointment_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_voice_calls_external_id ON voice_call_records(external_call_id);
CREATE INDEX IF NOT EXISTS idx_voice_calls_appointment_id ON voice_call_records(appointment_id);
CREATE INDEX IF NOT EXISTS idx_voice_calls_idempotency_key ON voice_call_records(idempotency_key);

-- Phase 14: External events & callback idempotency tracking
CREATE TABLE IF NOT EXISTS external_events (
    event_id TEXT PRIMARY KEY,
    event_source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    processed_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_external_events_idempotency ON external_events(idempotency_key);
"""


class SchemaMigrator:
    """Manages schema version detection and migration execution."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    def get_current_version(self) -> int:
        """Query the highest applied migration version."""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if not cursor.fetchone():
                return 0
            cursor.execute("SELECT MAX(version) AS max_ver FROM schema_version")
            row = cursor.fetchone()
            if row:
                if isinstance(row, dict):
                    val = row.get("max_ver")
                else:
                    val = row[0]
                if val is not None:
                    return int(val)
            return 0
        finally:
            cursor.close()

    def apply_migrations(self) -> int:
        """Apply all pending migrations up to CURRENT_SCHEMA_VERSION.
        
        Returns:
            The newly active schema version.
        """
        current = self.get_current_version()
        if current >= CURRENT_SCHEMA_VERSION:
            logger.debug("Database schema is up to date at version %d", current)
            return current

        cursor = self.conn.cursor()
        try:
            if current < 1:
                logger.info("Applying database migration to version 1...")
                cursor.executescript(MIGRATION_V1_DDL)
                now = datetime.utcnow().isoformat()
                cursor.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (1, now, "Initial Module 10 persistence schema"),
                )
                self.conn.commit()
                logger.info("Successfully applied database migration to version 1.")
            if current < 2:
                logger.info("Applying database migration to version 2...")
                cursor.executescript(MIGRATION_V2_DDL)
                now = datetime.utcnow().isoformat()
                cursor.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (2, now, "Phase 14 appointment and voice coordination schema"),
                )
                self.conn.commit()
                logger.info("Successfully applied database migration to version 2.")
            return CURRENT_SCHEMA_VERSION
        except Exception as e:
            self.conn.rollback()
            logger.error("Database migration failed: %s", str(e))
            raise RuntimeError(f"Database migration failed: {e}") from e
        finally:
            cursor.close()
