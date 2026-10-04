"""Module 10: Aarogya Durable Persistence Layer.

Exports storage engines, repositories, and persistence bundle factories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import get_settings
from .base import (
    StorageEngine,
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
from .migrations import SchemaMigrator, CURRENT_SCHEMA_VERSION
from .repositories import (
    SQLiteCapabilityRepository,
    SQLiteSyncHistoryRepository,
    SQLiteExecutionRepository,
    SQLiteIdempotencyRepository,
    SQLiteApprovalRepository,
    SQLiteAuditRepository,
    SQLiteAppointmentRepository,
    SQLiteVoiceRepository,
)


@dataclass
class PersistenceBundle:
    """Convenient bundle containing initialized storage store and all domain repositories."""
    store: SQLiteStore
    capability_repo: SQLiteCapabilityRepository
    sync_history_repo: SQLiteSyncHistoryRepository
    execution_repo: SQLiteExecutionRepository
    idempotency_repo: SQLiteIdempotencyRepository
    approval_repo: SQLiteApprovalRepository
    audit_repo: SQLiteAuditRepository
    appointment_repo: Optional[SQLiteAppointmentRepository] = None
    voice_repo: Optional[SQLiteVoiceRepository] = None


def get_persistence_bundle(db_path: Optional[str] = None) -> PersistenceBundle:
    """Instantiate and initialize the SQLite persistence bundle."""
    if db_path is None:
        settings = get_settings()
        db_path = settings.database_path

    store = SQLiteStore(db_path=db_path, auto_init=True)
    return PersistenceBundle(
        store=store,
        capability_repo=SQLiteCapabilityRepository(store),
        sync_history_repo=SQLiteSyncHistoryRepository(store),
        execution_repo=SQLiteExecutionRepository(store),
        idempotency_repo=SQLiteIdempotencyRepository(store),
        approval_repo=SQLiteApprovalRepository(store),
        audit_repo=SQLiteAuditRepository(store),
        appointment_repo=SQLiteAppointmentRepository(store),
        voice_repo=SQLiteVoiceRepository(store),
    )


__all__ = [
    "StorageEngine",
    "CapabilityRepository",
    "SyncHistoryRepository",
    "ExecutionRepository",
    "IdempotencyRepository",
    "ApprovalRepository",
    "AuditRepository",
    "AppointmentRepository",
    "VoiceRepository",
    "SQLiteStore",
    "SchemaMigrator",
    "CURRENT_SCHEMA_VERSION",
    "SQLiteCapabilityRepository",
    "SQLiteSyncHistoryRepository",
    "SQLiteExecutionRepository",
    "SQLiteIdempotencyRepository",
    "SQLiteApprovalRepository",
    "SQLiteAuditRepository",
    "SQLiteAppointmentRepository",
    "SQLiteVoiceRepository",
    "PersistenceBundle",
    "get_persistence_bundle",
]
