"""Health and Readiness Endpoints for Aarogya API."""

from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel

from ...config import get_settings
from ...persistence.migrations import CURRENT_SCHEMA_VERSION

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Non-sensitive system health and readiness payload."""
    status: str
    service: str
    version: str
    execution_mode: str
    live_execution_enabled: bool
    schema_version: int
    timestamp: str
    components: dict


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return non-sensitive system health status and component readiness."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service="Aarogya Healthcare Coordination Platform",
        version="1.0.0",
        execution_mode=settings.execution_mode.value,
        live_execution_enabled=settings.live_execution_enabled,
        schema_version=CURRENT_SCHEMA_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components={
            "execution_gateway": "ready",
            "persistence": "sqlite_v2",
            "appointment_workflow": "active",
            "voice_coordination": "simulated",
            "hitl_approvals": "active",
        },
    )
