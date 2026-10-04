"""Module 5: Human-in-the-Loop (HITL) Approval Manager."""

import logging
from typing import Dict, Optional, Any
from datetime import datetime
from ..models.approval import ApprovalRecord, compute_parameter_hash
from ..models.enums import ApprovalStatus, ActionType

# Type alias for return tuple: (success: bool, message: str, record: Optional[ApprovalRecord])
TupleApprovalResult = tuple[bool, str, Optional[ApprovalRecord]]

logger = logging.getLogger(__name__)


class ApprovalManager:
    """Manages explicit human approval requests, bindings, and status tracking."""

    def __init__(self, default_validity_minutes: int = 60, approval_repo: Optional[Any] = None):
        self.default_validity_minutes = default_validity_minutes
        self.approval_repo = approval_repo
        self._approvals: Dict[str, ApprovalRecord] = {}

    def request_approval(
        self,
        request_id: str,
        user_identity: str,
        action_type: ActionType,
        parameters: Dict[str, Any],
        is_simulation: bool = False,
    ) -> ApprovalRecord:
        """Create a new pending approval record bound to specific operation parameters."""
        record = ApprovalRecord.create_pending(
            request_id=request_id,
            user_identity=user_identity,
            action_type=action_type,
            parameters=parameters,
            validity_minutes=self.default_validity_minutes,
            is_simulation=is_simulation,
        )
        self._approvals[record.approval_id] = record
        if self.approval_repo:
            try:
                self.approval_repo.save_approval(record)
            except Exception as e:
                logger.error("Failed to persist approval request: %s", str(e))
        logger.info(
            "Created approval request %s for user %s, action %s (hash: %s)",
            record.approval_id,
            user_identity,
            action_type.value,
            record.parameter_hash,
        )
        return record

    def grant_approval(
        self,
        approval_id: str,
        user_identity: str,
        provided_parameters: Optional[Dict[str, Any]] = None,
    ) -> TupleApprovalResult:
        """Grant an approval, verifying identity, expiration, and parameter consistency."""
        record = self.get_approval(approval_id)
        if not record:
            return False, f"Approval ID '{approval_id}' not found.", None

        if record.approval_status != ApprovalStatus.PENDING:
            return False, f"Approval is not in PENDING state (current: {record.approval_status.value}).", record

        if datetime.utcnow() > record.expiration:
            record.approval_status = ApprovalStatus.EXPIRED
            if self.approval_repo:
                try:
                    self.approval_repo.save_approval(record)
                except Exception:
                    pass
            return False, "Approval has expired. A fresh approval must be requested.", record

        # Strict identity check: only authorized user can grant
        if record.user_identity != user_identity:
            return False, f"User '{user_identity}' is not authorized to grant approval requested for '{record.user_identity}'.", record

        # Material parameter modification check
        if provided_parameters is not None:
            provided_hash = compute_parameter_hash(provided_parameters)
            if provided_hash != record.parameter_hash:
                record.approval_status = ApprovalStatus.REVOKED
                if self.approval_repo:
                    try:
                        self.approval_repo.save_approval(record)
                    except Exception:
                        pass
                return (
                    False,
                    "Parameters changed materially from original request. Approval revoked; re-approval required.",
                    record,
                )

        record.approval_status = ApprovalStatus.GRANTED
        record.granted_by = user_identity
        record.granted_at = datetime.utcnow()
        self._approvals[record.approval_id] = record
        if self.approval_repo:
            try:
                self.approval_repo.save_approval(record)
            except Exception as e:
                logger.error("Failed to persist granted approval: %s", str(e))
        logger.info("Approval %s successfully GRANTED by %s", approval_id, user_identity)
        return True, "Approval granted successfully.", record

    def reject_approval(
        self,
        approval_id: str,
        user_identity: str,
        reason: str = "User declined operation",
    ) -> TupleApprovalResult:
        """Explicitly reject an approval."""
        record = self.get_approval(approval_id)
        if not record:
            return False, f"Approval ID '{approval_id}' not found.", None

        record.approval_status = ApprovalStatus.REJECTED
        record.rejection_reason = reason
        self._approvals[record.approval_id] = record
        if self.approval_repo:
            try:
                self.approval_repo.save_approval(record)
            except Exception as e:
                logger.error("Failed to persist rejected approval: %s", str(e))
        logger.info("Approval %s REJECTED by %s: %s", approval_id, user_identity, reason)
        return True, f"Approval rejected: {reason}", record

    def get_approval(self, approval_id: str) -> Optional[ApprovalRecord]:
        record = self._approvals.get(approval_id)
        if record:
            return record
        if self.approval_repo:
            try:
                persisted = self.approval_repo.get_approval(approval_id)
                if persisted:
                    self._approvals[approval_id] = persisted
                    return persisted
            except Exception as e:
                logger.warning("Could not fetch approval from repository: %s", str(e))
        return None
