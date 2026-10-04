"""Structured Audit and Event Logger."""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from ..models.audit import AuditLogEntry
from ..models.enums import AuditEventType, ExecutionMode

logger = logging.getLogger("aarogya.audit")


class AuditLogger:
    """Structured audit trail recorder preserving privacy and redacting secrets."""

    def __init__(
        self,
        log_file: Optional[str] = "aarogya_audit.log",
        redact_sensitive: bool = True,
        audit_repo: Optional[Any] = None,
    ):
        self.log_file = log_file
        self.redact_sensitive = redact_sensitive
        self.audit_repo = audit_repo
        self._in_memory_logs: List[AuditLogEntry] = []

    def log(
        self,
        event_type: AuditEventType,
        status: str,
        details: str,
        request_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        user_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.SIMULATION,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditLogEntry:
        """Create and store a structured audit entry."""
        meta = metadata or {}
        if self.redact_sensitive:
            meta = self._redact(meta)

        entry = AuditLogEntry(
            event_type=event_type,
            status=status,
            details=details,
            request_id=request_id,
            patient_id=patient_id,
            user_id=user_id,
            operation_type=operation_type,
            execution_mode=execution_mode,
            metadata=meta,
            timestamp=datetime.utcnow(),
        )

        self._in_memory_logs.append(entry)

        # Persist to durable audit repository
        if self.audit_repo:
            try:
                self.audit_repo.record_event(entry)
            except Exception as e:
                logger.error("Failed to record audit event to database: %s", str(e))

        # Write to log file if specified
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(entry.model_dump_json() + "\n")
            except Exception as e:
                logger.error("Failed to write to audit log file: %s", str(e))

        logger.info(
            "AUDIT [%s] %s | req=%s | pat=%s | user=%s | %s",
            event_type.value,
            status,
            request_id,
            patient_id,
            user_id,
            details,
        )
        return entry

    def _redact(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive fields (passwords, tokens, phone numbers, raw card numbers)."""
        redacted = {}
        sensitive_keys = ["token", "key", "password", "secret", "auth", "phone", "card", "cvv"]
        for k, v in data.items():
            if any(s in k.lower() for s in sensitive_keys):
                redacted[k] = "[REDACTED]"
            elif isinstance(v, dict):
                redacted[k] = self._redact(v)
            else:
                redacted[k] = v
        return redacted

    def get_entries_for_request(self, request_id: str) -> List[AuditLogEntry]:
        if self.audit_repo:
            try:
                entries = self.audit_repo.list_events(request_id=request_id)
                if entries:
                    return entries
            except Exception:
                pass
        return [e for e in self._in_memory_logs if e.request_id == request_id]

    def get_all_entries(self) -> List[AuditLogEntry]:
        if self.audit_repo:
            try:
                entries = self.audit_repo.list_events()
                if entries:
                    return entries
            except Exception:
                pass
        return list(self._in_memory_logs)

    def import_from_jsonl(self, jsonl_path: Optional[str] = None) -> int:
        """Explicit safe import of JSONL audit records into database."""
        path = jsonl_path or self.log_file
        if not path or not self.audit_repo:
            return 0
        return self.audit_repo.import_from_jsonl(path)
