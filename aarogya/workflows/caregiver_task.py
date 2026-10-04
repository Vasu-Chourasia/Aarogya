"""Module 4: Caregiver Task Creation and Orchestration Workflow."""

import logging
from typing import Optional, Dict, Any, Tuple
from ..brain.family_health_brain import FamilyHealthBrain
from ..connectors.registry import ConnectorRegistry
from ..connectors.task_connector import TaskBackendInterface, LocalDevelopmentTaskBackend
from ..policy.authorization_engine import PolicyAuthorizationEngine
from .approval_manager import ApprovalManager
from .verification import OutcomeVerificationService
from ..models.task import CaregiverTask, CaregiverTaskCreateRequest
from ..models.enums import TaskStatus, ActionType, ApprovalStatus, ExecutionMode

logger = logging.getLogger(__name__)


class CaregiverTaskWorkflow:
    """Manages the creation, approval, and execution tracking of caregiver tasks."""

    def __init__(
        self,
        brain: FamilyHealthBrain,
        connector_registry: ConnectorRegistry,
        policy_engine: PolicyAuthorizationEngine,
        approval_manager: ApprovalManager,
        task_backend: Optional[TaskBackendInterface] = None,
        verification_service: Optional[OutcomeVerificationService] = None,
    ):
        self.brain = brain
        self.connector_registry = connector_registry
        self.policy_engine = policy_engine
        self.approval_manager = approval_manager
        self.task_backend = task_backend or LocalDevelopmentTaskBackend()
        self.verification_service = verification_service or OutcomeVerificationService()

    def propose_task(
        self,
        request_id: str,
        user_id: str,
        patient_id: str,
        task_description: str,
        assigned_caregiver: str,
        medicine_reference: Optional[str] = None,
        required_quantity: Optional[int] = None,
        priority: str = "NORMAL",
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Propose creating a caregiver task and submit to approval gate.
        
        Task creation is consequential and requires explicit human approval.
        """
        # Step 1: Policy check
        is_auth, auth_reason = self.policy_engine.authorize_request(
            user_id=user_id,
            patient_id=patient_id,
            action="create_caregiver_task",
        )
        if not is_auth:
            return False, f"Unauthorized: {auth_reason}", None

        # Step 2: Prepare approval request with exact bound parameters
        parameters = {
            "patient_id": patient_id,
            "task_description": task_description,
            "assigned_caregiver": assigned_caregiver,
            "medicine_reference": medicine_reference,
            "required_quantity": required_quantity,
            "priority": priority,
        }

        is_sim = self.connector_registry.execution_mode == ExecutionMode.SIMULATION
        approval_record = self.approval_manager.request_approval(
            request_id=request_id,
            user_identity=user_id,
            action_type=ActionType.CREATE_CAREGIVER_TASK,
            parameters=parameters,
            is_simulation=is_sim,
        )

        return (
            True,
            f"Caregiver task proposal drafted. Awaiting explicit human approval (Approval ID: {approval_record.approval_id}).",
            {
                "approval_id": approval_record.approval_id,
                "status": "awaiting_approval",
                "proposed_task": parameters,
            },
        )

    def execute_approved_task_creation(
        self,
        approval_id: str,
        user_id: str,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[CaregiverTask]]:
        """Executes task creation after verifying valid approval.
        
        Bound strictly to the approved parameters.
        Does NOT authorize medicine orders or payments.
        """
        approval = self.approval_manager.get_approval(approval_id)
        if not approval:
            return False, f"Approval ID '{approval_id}' not found.", None

        if approval.approval_status != ApprovalStatus.GRANTED:
            return (
                False,
                f"Cannot create task: Approval is not in GRANTED state (current: {approval.approval_status.value}).",
                None,
            )

        params = approval.relevant_parameters
        
        # Capability check on task backend
        is_sim_mode = self.connector_registry.execution_mode == ExecutionMode.SIMULATION
        cap_check = self.connector_registry.check_capability(
            integration="task_manager",
            required_capability="create_caregiver_task",
            allow_simulation=is_sim_mode,
        )

        if not cap_check.available and not is_sim_mode:
            return (
                False,
                f"Task management backend unavailable: {cap_check.reason}. No real-world task backend configured.",
                None,
            )

        # Create execution record
        exec_record = self.verification_service.create_execution_record(
            request_id=approval.request_id,
            operation_type="caregiver_task_creation",
            status="executing",
        )

        create_req = CaregiverTaskCreateRequest(
            patient_id=params["patient_id"],
            medicine_reference=params.get("medicine_reference"),
            required_quantity=params.get("required_quantity"),
            task_description=params["task_description"],
            assigned_caregiver=params["assigned_caregiver"],
            approval_reference=approval_id,
            idempotency_key=idempotency_key,
        )

        task = self.task_backend.create_task(create_req)

        # Record verified execution
        self.verification_service.record_execution_success(
            operation_id=exec_record.operation_id,
            provider_response={
                "task_id": task.task_id,
                "status": task.current_status.value,
                "backend_type": task.backend_type,
                "is_simulation": task.is_simulation,
            },
            evidence_description=f"Task {task.task_id} successfully registered in {task.backend_type}",
            evidence_source=task.backend_type,
            is_delivery_or_clinical=False,
        )

        return True, f"Caregiver task created successfully (Task ID: {task.task_id}).", task
