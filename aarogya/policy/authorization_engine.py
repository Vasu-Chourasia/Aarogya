"""Healthcare Policy and Authorization Engine."""

from typing import Tuple, Optional, Dict, Any
from ..brain.family_health_brain import FamilyHealthBrain
from ..models.enums import ActionType


class PolicyAuthorizationEngine:
    """Evaluates access control, family circle permissions, and consequential action policies."""

    def __init__(self, brain: FamilyHealthBrain):
        self.brain = brain

    def is_consequential_action(self, action: str) -> bool:
        """Identify whether an action requires strict human approval."""
        consequential_actions = [
            ActionType.CREATE_CAREGIVER_TASK.value,
            ActionType.PLACE_MEDICINE_ORDER.value,
            ActionType.BOOK_APPOINTMENT.value,
            ActionType.INITIATE_PAYMENT.value,
            ActionType.MODIFY_HEALTHCARE_RECORD.value,
            ActionType.SEND_HEALTHCARE_COMMUNICATION.value,
            "create_task",
            "order_medicine",
            "book_appointment",
            "pay",
        ]
        return action.lower() in [a.lower() for a in consequential_actions]

    def authorize_request(
        self,
        user_id: str,
        patient_id: str,
        action: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Verify if requesting user is authorized to perform action for patient.
        
        Returns (is_authorized, reason).
        """
        patient = self.brain.get_patient(patient_id)
        if not patient:
            return False, f"Patient record '{patient_id}' not found in Family Health Brain."

        # Find member record in patient's family circle
        member_match = next((m for m in patient.family_members if m.member_id == user_id), None)
        if not member_match:
            return False, f"User '{user_id}' is not authorized: not in patient '{patient.full_name}' family circle."

        # Map action to required permission
        required_permission = self._get_required_permission(action)
        if required_permission not in member_match.permissions:
            return False, f"User '{user_id}' lacks required permission '{required_permission}' for this patient."

        # Policy checks for clinical safety
        if "modify_dosage" in action or "change_medicine" in action:
            return False, "Clinical safety policy violation: Agent cannot alter prescribed medications independently."

        return True, "Authorized by family healthcare policy."

    def _get_required_permission(self, action: str) -> str:
        act = action.lower()
        if "availability" in act or "check" in act:
            return "check_medicine"
        if "task" in act:
            return "create_tasks"
        if "order" in act or "buy" in act:
            return "approve_orders"
        if "pay" in act:
            return "approve_orders"
        if "book" in act:
            return "approve_orders"
        if "appointment" in act:
            return "create_tasks"
        return "view_records"
