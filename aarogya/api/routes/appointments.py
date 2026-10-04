"""Appointment Management Endpoints for Aarogya API."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel, Field

from ...models.appointment import (
    AppointmentRequest,
    AppointmentRecord,
    AppointmentSlotApprovalRequest,
)
from ...workflows.appointment_coordination import AppointmentCoordinationWorkflow
from ..security import get_current_user_or_api_client

router = APIRouter(tags=["Appointments"])


def get_workflow(request: Request) -> AppointmentCoordinationWorkflow:
    """Retrieve the AppointmentCoordinationWorkflow from application state."""
    if hasattr(request.app.state, "appointment_workflow") and request.app.state.appointment_workflow:
        return request.app.state.appointment_workflow
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Appointment coordination workflow service unavailable.",
    )


class SlotApprovalBody(BaseModel):
    """Input payload for approving an offered appointment slot."""
    approving_user_id: str
    slot_id: str
    approval_notes: Optional[str] = None
    idempotency_key: Optional[str] = None


@router.post(
    "/appointments",
    response_model=AppointmentRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate appointment coordination",
)
def create_appointment(
    request_data: AppointmentRequest,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> AppointmentRecord:
    """Create an authorized appointment coordination request and initiate clinic slot discovery."""
    success, message, record = workflow.initiate_coordination(request_data)

    if not success:
        if "emergency" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "EMERGENCY_DETECTED", "message": message},
            )
        if "unauthorized" in message.lower() or "not authorized" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "UNAUTHORIZED", "message": message},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "COORDINATION_FAILED", "message": message},
        )

    return record


@router.get(
    "/appointments/{appointment_id}",
    response_model=AppointmentRecord,
    summary="Retrieve appointment by ID",
)
def get_appointment(
    appointment_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> AppointmentRecord:
    """Retrieve appointment details permitted by family circle authorization."""
    record = workflow._get_record(appointment_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment '{appointment_id}' not found.",
        )

    # Enforce family circle authorization if user_id is provided
    user_id = x_user_id or record.requesting_user_id
    is_auth, reason = workflow.policy_engine.authorize_request(
        user_id=user_id,
        patient_id=record.patient_id,
        action="view_records",
    )
    if not is_auth:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {reason}",
        )

    return record


@router.post(
    "/appointments/{appointment_id}/approve-slot",
    response_model=AppointmentRecord,
    summary="Record approved slot and confirm booking",
)
def approve_appointment_slot(
    appointment_id: str,
    body: SlotApprovalBody,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> AppointmentRecord:
    """Explicitly authorize slot selection. Autonomous slot selection is forbidden."""
    approval_req = AppointmentSlotApprovalRequest(
        appointment_id=appointment_id,
        approving_user_id=body.approving_user_id,
        slot_id=body.slot_id,
        approval_notes=body.approval_notes,
        idempotency_key=body.idempotency_key,
    )

    success, message, record = workflow.approve_and_book_slot(approval_req)

    if not success:
        if "not found" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            )
        if "unauthorized" in message.lower() or "lacks required permission" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=message,
            )
        if "not in the list" in message.lower() or "rejected" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return record
