"""Voice Integration and Webhook Endpoints for Aarogya API."""

from __future__ import annotations

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel

from ...models.voice import VoiceCallOutcomeEvent, VoiceContextResponse
from ...models.appointment import AppointmentRecord
from ...workflows.appointment_coordination import AppointmentCoordinationWorkflow
from ..security import get_current_user_or_api_client, verify_gnani_callback_auth

router = APIRouter(tags=["Voice & Integrations"])


def get_workflow(request: Request) -> AppointmentCoordinationWorkflow:
    """Retrieve the AppointmentCoordinationWorkflow from application state."""
    if hasattr(request.app.state, "appointment_workflow") and request.app.state.appointment_workflow:
        return request.app.state.appointment_workflow
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Appointment coordination workflow service unavailable.",
    )


class VoiceOutcomeResponse(BaseModel):
    """Response payload returned following webhook ingestion."""
    status: str
    message: str
    appointment: Optional[AppointmentRecord] = None


@router.get(
    "/voice/appointments/{appointment_id}/context",
    response_model=VoiceContextResponse,
    summary="Retrieve minimal authorized voice coordination context",
)
def get_voice_context(
    appointment_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> VoiceContextResponse:
    """Return only non-sensitive, authorized minimal context needed for voice clinic coordination."""
    rec = workflow._get_record(appointment_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment '{appointment_id}' not found.",
        )

    user_id = x_user_id or rec.requesting_user_id
    success, message, context = workflow.get_voice_context(appointment_id, user_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=message,
        )

    return context


@router.post(
    "/integrations/gnani/call-outcome",
    response_model=VoiceOutcomeResponse,
    status_code=status.HTTP_200_OK,
    summary="Record incoming voice call outcome event from Gnani.ai",
)
def record_voice_outcome(
    outcome: VoiceCallOutcomeEvent,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: bool = Depends(verify_gnani_callback_auth),
) -> VoiceOutcomeResponse:
    """Process a validated voice outcome event from the voice coordination agent.
    
    Enforces webhook idempotency and rejects duplicate state changes.
    """
    success, message, record = workflow.process_voice_outcome(outcome)

    if not success and not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )

    return VoiceOutcomeResponse(
        status="processed",
        message=message,
        appointment=record,
    )
