"""Module 10: Persistence Base Abstractions and Interfaces.

Provides abstract repositories and storage engine contracts so business and
healthcare policy logic remain decoupled from the underlying database implementation
(supporting SQLite now and seamless future migration to PostgreSQL).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from ..models.connector import NormalizedCapability, SyncHistoryRecord
from ..models.approval import ApprovalRecord
from ..models.gateway import ExecutionRequest, ExecutionResult
from ..models.audit import AuditLogEntry
from ..models.enums import GatewayExecutionStatus, ApprovalStatus


class StorageEngine(ABC):
    """Abstract interface for database connection and transaction management."""

    @abstractmethod
    def initialize(self) -> None:
        """Run schema migrations and initialize connection pool / settings."""
        pass

    @abstractmethod
    def transaction(self):
        """Context manager yielding a transactional connection / cursor."""
        pass

    @abstractmethod
    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> Any:
        """Execute a single query with parameters."""
        pass

    @abstractmethod
    def fetchone(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single record as a dictionary."""
        pass

    @abstractmethod
    def fetchall(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        """Fetch all matching records as dictionaries."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connections."""
        pass


class CapabilityRepository(ABC):
    """Abstract repository for connector and MCP capabilities."""

    @abstractmethod
    def save(self, capability: NormalizedCapability) -> None:
        """Persist or update a normalized capability."""
        pass

    @abstractmethod
    def save_all(self, capabilities: List[NormalizedCapability]) -> None:
        """Persist or update a batch of capabilities within a transaction."""
        pass

    @abstractmethod
    def get(self, capability_id: str) -> Optional[NormalizedCapability]:
        """Retrieve capability by ID."""
        pass

    @abstractmethod
    def list_all(self, include_stale: bool = True) -> List[NormalizedCapability]:
        """List all capabilities, optionally filtering stale ones."""
        pass

    @abstractmethod
    def mark_stale(self, capability_id: str) -> None:
        """Mark a capability as stale."""
        pass

    @abstractmethod
    def count(self) -> int:
        """Count total persisted capabilities."""
        pass


class SyncHistoryRepository(ABC):
    """Abstract repository for synchronization history records."""

    @abstractmethod
    def record_sync(self, sync_record: SyncHistoryRecord) -> None:
        """Persist a synchronization history record."""
        pass

    @abstractmethod
    def get_latest_sync(self) -> Optional[SyncHistoryRecord]:
        """Retrieve the most recent synchronization record."""
        pass

    @abstractmethod
    def list_syncs(self, limit: int = 50) -> List[SyncHistoryRecord]:
        """List past synchronization records ordered descending by time."""
        pass


class ExecutionRepository(ABC):
    """Abstract repository for execution records and lifecycle transitions."""

    @abstractmethod
    def save_execution(self, execution: ExecutionResult, request: Optional[ExecutionRequest] = None) -> None:
        """Persist or update an execution result."""
        pass

    @abstractmethod
    def get_execution(self, execution_id: str) -> Optional[ExecutionResult]:
        """Retrieve an execution result by ID."""
        pass

    @abstractmethod
    def get_by_request_id(self, request_id: str) -> Optional[ExecutionResult]:
        """Retrieve execution by request ID."""
        pass

    @abstractmethod
    def list_executions(self, limit: int = 50, user_id: Optional[str] = None) -> List[ExecutionResult]:
        """List executions ordered descending by timestamp."""
        pass

    @abstractmethod
    def update_status(
        self,
        execution_id: str,
        status: GatewayExecutionStatus,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update execution status."""
        pass

    @abstractmethod
    def recover_interrupted_executions(self) -> List[str]:
        """Identify interrupted in-flight executions on startup and mark them UNKNOWN_OUTCOME."""
        pass


class IdempotencyRepository(ABC):
    """Abstract repository for duplicate protection and concurrent execution claims."""

    @abstractmethod
    def claim_key(
        self,
        idempotency_key: str,
        execution_id: str,
        user_id: Optional[str],
        operation: str,
        request_fingerprint: str,
    ) -> bool:
        """Attempt to claim an idempotency key before dispatch.
        
        Returns:
            True if key was successfully claimed (first attempt).
            False if key already exists (duplicate attempt).
        """
        pass

    @abstractmethod
    def get_record(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve raw idempotency record by key."""
        pass

    @abstractmethod
    def update_status(self, idempotency_key: str, status: str) -> None:
        """Update state of an existing idempotency claim."""
        pass


class ApprovalRepository(ABC):
    """Abstract repository for HITL human approval records."""

    @abstractmethod
    def save_approval(self, approval: ApprovalRecord) -> None:
        """Persist or update an approval record."""
        pass

    @abstractmethod
    def get_approval(self, approval_id: str) -> Optional[ApprovalRecord]:
        """Retrieve an approval record by ID."""
        pass

    @abstractmethod
    def update_status(
        self,
        approval_id: str,
        status: ApprovalStatus,
        granted_by: Optional[str] = None,
        rejection_reason: Optional[str] = None,
    ) -> None:
        """Update approval status, granter, and timestamps."""
        pass

    @abstractmethod
    def list_pending(self, user_identity: Optional[str] = None) -> List[ApprovalRecord]:
        """List pending approvals."""
        pass


class AuditRepository(ABC):
    """Abstract repository for structured audit events."""

    @abstractmethod
    def record_event(self, entry: AuditLogEntry) -> None:
        """Persist a structured audit event."""
        pass

    @abstractmethod
    def list_events(
        self,
        limit: int = 100,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[AuditLogEntry]:
        """List audit events ordered descending by timestamp."""
        pass

    @abstractmethod
    def import_from_jsonl(self, jsonl_path: str) -> int:
        """Safely import existing JSONL audit entries without duplicates."""
        pass


class AppointmentRepository(ABC):
    """Abstract repository for durable healthcare appointment records."""

    @abstractmethod
    def save(self, record: Any) -> None:
        """Persist or update an appointment record."""
        pass

    @abstractmethod
    def get(self, appointment_id: str) -> Optional[Any]:
        """Retrieve an appointment by its ID."""
        pass

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Any]:
        """Retrieve an appointment by idempotency key."""
        pass

    @abstractmethod
    def list_by_patient(self, patient_id: str) -> List[Any]:
        """List appointments for a specific patient."""
        pass

    @abstractmethod
    def update_status(
        self,
        appointment_id: str,
        status: Any,
        failure_reason: Optional[str] = None,
        clinic_booking_reference: Optional[str] = None,
        approved_slot: Optional[Any] = None,
    ) -> None:
        """Update appointment lifecycle status and associated outcomes."""
        pass


class VoiceRepository(ABC):
    """Abstract repository for external voice coordination calls and callbacks."""

    @abstractmethod
    def save_call(self, call: Any) -> None:
        """Persist or update a voice call record."""
        pass

    @abstractmethod
    def get_call(self, call_id: str) -> Optional[Any]:
        """Retrieve a voice call record by internal call_id."""
        pass

    @abstractmethod
    def get_by_external_id(self, external_call_id: str) -> Optional[Any]:
        """Retrieve a voice call record by external_call_id."""
        pass

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Any]:
        """Retrieve a voice call record by idempotency key."""
        pass

    @abstractmethod
    def list_by_appointment(self, appointment_id: str) -> List[Any]:
        """List all voice call sessions for an appointment."""
        pass

    @abstractmethod
    def record_external_event(
        self,
        event_id: str,
        event_source: str,
        event_type: str,
        idempotency_key: str,
        payload: str,
        status: str = "PROCESSED",
    ) -> bool:
        """Atomically record an incoming external event, returning False if duplicate."""
        pass

    @abstractmethod
    def get_external_event(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a recorded external event by idempotency key."""
        pass
