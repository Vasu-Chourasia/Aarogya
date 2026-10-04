"""Caregiver Task Connector Interface and Implementations."""

import logging
from typing import Optional, Dict, List
import uuid
from ..models.task import CaregiverTask, CaregiverTaskCreateRequest
from ..models.enums import TaskStatus

logger = logging.getLogger(__name__)


class TaskBackendInterface:
    """Abstract interface for caregiver task management."""
    
    def create_task(self, req: CaregiverTaskCreateRequest) -> CaregiverTask:
        raise NotImplementedError
        
    def get_task(self, task_id: str) -> Optional[CaregiverTask]:
        raise NotImplementedError

    def update_task_status(self, task_id: str, new_status: TaskStatus, evidence: Optional[str] = None) -> Optional[CaregiverTask]:
        raise NotImplementedError


class LocalDevelopmentTaskBackend(TaskBackendInterface):
    """Clearly labeled local development mock task backend.
    
    Stores tasks in-memory and explicitly marks them as simulated/local.
    Never claims to be a production backend.
    """

    def __init__(self):
        self._tasks: Dict[str, CaregiverTask] = {}
        self._idempotency_map: Dict[str, str] = {}  # idempotency_key -> task_id

    def create_task(self, req: CaregiverTaskCreateRequest) -> CaregiverTask:
        # Idempotency check
        if req.idempotency_key and req.idempotency_key in self._idempotency_map:
            existing_id = self._idempotency_map[req.idempotency_key]
            logger.info("Idempotent task request matched existing task %s", existing_id)
            return self._tasks[existing_id]

        new_task = CaregiverTask(
            task_id=f"tsk_local_{uuid.uuid4().hex[:8]}",
            patient_id=req.patient_id,
            medicine_reference=req.medicine_reference,
            required_quantity=req.required_quantity,
            task_description=req.task_description,
            assigned_caregiver=req.assigned_caregiver,
            priority=req.priority,
            due_date=req.due_date,
            approval_reference=req.approval_reference,
            current_status=TaskStatus.APPROVED,  # Since valid approval was provided
            outcome_evidence=[f"Created in local development backend with approval {req.approval_reference}"],
            is_simulation=True,
            backend_type="local_development_task_backend",
            idempotency_key=req.idempotency_key,
        )
        self._tasks[new_task.task_id] = new_task
        if req.idempotency_key:
            self._idempotency_map[req.idempotency_key] = new_task.task_id
        return new_task

    def get_task(self, task_id: str) -> Optional[CaregiverTask]:
        return self._tasks.get(task_id)

    def update_task_status(
        self, task_id: str, new_status: TaskStatus, evidence: Optional[str] = None
    ) -> Optional[CaregiverTask]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.current_status = new_status
        if evidence:
            task.outcome_evidence.append(evidence)
        return task

    def list_tasks_for_patient(self, patient_id: str) -> List[CaregiverTask]:
        return [t for t in self._tasks.values() if t.patient_id == patient_id]
