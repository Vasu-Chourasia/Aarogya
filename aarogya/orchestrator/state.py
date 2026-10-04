"""LangGraph State Schema for Aarogya Agent."""

from typing import TypedDict, Optional, Dict, Any, List
from ..models.request import HealthcareRequest, ParsedRequest
from ..models.connector import CapabilityCheckResult
from ..models.medicine import MedicineAvailabilityResult
from ..models.task import CaregiverTask
from ..models.approval import ApprovalRecord
from ..models.execution import ExecutionRecord
from ..models.enums import ExecutionStatus


class AarogyaAgentState(TypedDict, total=False):
    """Execution state passed through the LangGraph StateGraph."""
    raw_request: HealthcareRequest
    parsed_request: Optional[ParsedRequest]
    patient_resolved: bool
    patient_id: Optional[str]
    patient_name: Optional[str]
    prescription_verified: bool
    prescription_id: Optional[str]
    is_authorized: bool
    authorization_reason: Optional[str]
    is_consequential: bool
    capability_check: Optional[CapabilityCheckResult]
    execution_status: ExecutionStatus
    approval_record: Optional[ApprovalRecord]
    medicine_result: Optional[MedicineAvailabilityResult]
    task_result: Optional[CaregiverTask]
    execution_record: Optional[ExecutionRecord]
    final_response: Dict[str, Any]
    error_message: Optional[str]
