"""FastAPI Application Factory for Aarogya Healthcare Coordination Platform."""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import Settings, get_settings
from ..brain.family_health_brain import FamilyHealthBrain
from ..policy.authorization_engine import PolicyAuthorizationEngine
from ..workflows.appointment_coordination import AppointmentCoordinationWorkflow
from ..persistence import get_persistence_bundle
from .routes.health import router as health_router
from .routes.appointments import router as appointments_router
from .routes.voice import router as voice_router
from .routes.mcp import router as mcp_router
from .routes.mcp_readonly import router as mcp_readonly_router

logger = logging.getLogger(__name__)

# Max request body size: 1 MB
MAX_REQUEST_SIZE = 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforce request body size limits to prevent Denial-of-Service attacks."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_SIZE:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Request payload exceeds maximum allowed size (1MB)."},
                    )
            except ValueError:
                pass
        return await call_next(request)


def create_app(
    settings: Optional[Settings] = None,
    workflow: Optional[AppointmentCoordinationWorkflow] = None,
    brain: Optional[FamilyHealthBrain] = None,
) -> FastAPI:
    """Create and configure the Aarogya FastAPI application instance."""
    app_settings = settings or get_settings()

    app = FastAPI(
        title="Aarogya Healthcare Coordination API",
        version="1.0.0",
        description=(
            "Integration API for Aarogya Family Healthcare Coordination Platform. "
            "Governs appointment scheduling, patient authorization, human approvals, "
            "and clinic voice coordination via Gnani.ai."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Middleware
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # State initialization
    if workflow:
        app.state.appointment_workflow = workflow
    else:
        # Initialize default workflow backed by SQLite and Family Health Brain
        shared_brain = brain or FamilyHealthBrain()
        policy_engine = PolicyAuthorizationEngine(shared_brain)
        try:
            bundle = get_persistence_bundle(app_settings.database_path)
            app.state.appointment_workflow = AppointmentCoordinationWorkflow(
                brain=shared_brain,
                policy_engine=policy_engine,
                appointment_repo=bundle.appointment_repo,
                voice_repo=bundle.voice_repo,
            )
        except Exception as e:
            logger.warning("Could not initialize SQLite persistence bundle: %s; using in-memory defaults.", str(e))
            app.state.appointment_workflow = AppointmentCoordinationWorkflow(
                brain=shared_brain,
                policy_engine=policy_engine,
            )

    app.state.settings = app_settings

    # Include API Routers under /api/v1
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(appointments_router, prefix="/api/v1")
    app.include_router(voice_router, prefix="/api/v1")
    app.include_router(mcp_router, prefix="/api/v1")
    app.include_router(mcp_router, prefix="")
    app.include_router(mcp_readonly_router, prefix="/api/v1")
    app.include_router(mcp_readonly_router, prefix="")

    # Global Exception Handlers for safe, non-leaking responses
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("Validation error on %s: %s", request.url.path, str(exc))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Request payload validation failed.", "errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled internal server error on %s: %s", request.url.path, str(exc), exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal healthcare coordination processing error."},
        )

    return app
