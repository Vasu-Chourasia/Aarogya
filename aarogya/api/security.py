"""Security, Authentication, and Verification dependencies for Aarogya API."""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Optional
from fastapi import HTTPException, Security, Header, Request, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from ..config import get_settings, ExecutionMode

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)


def get_current_user_or_api_client(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth),
) -> str:
    """Validate inbound API authentication via X-API-Key or Bearer token."""
    settings = getattr(request.app.state, "settings", None) or get_settings()

    if not settings.api_auth_enabled:
        return "development_user"

    configured_secret = settings.api_key
    if not configured_secret:
        # Default safety: if auth enabled but no key configured, reject
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API authentication enabled but server API key is unconfigured.",
        )

    provided = None
    if api_key:
        provided = api_key
    elif bearer and bearer.credentials:
        provided = bearer.credentials

    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials missing. Provide 'X-API-Key' or 'Authorization: Bearer <token>' header.",
        )

    if not secrets.compare_digest(provided, configured_secret):
        logger.warning("Failed API authentication attempt.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API authentication token.",
        )

    return "authenticated_api_client"


def verify_gnani_callback_auth(
    request: Request,
    x_gnani_secret: Optional[str] = Header(None, alias="X-Gnani-Secret"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> bool:
    """Verify Gnani.ai webhook authenticity.
    
    Fail-closed policy: If in AUTHORIZED_EXECUTION mode and no secret is configured
    or provided, reject with 503 Service Unavailable / 401 Unauthorized.
    """
    settings = getattr(request.app.state, "settings", None) or get_settings()

    # If secret is explicitly configured
    if settings.gnani_webhook_secret:
        provided = x_gnani_secret
        if not provided and authorization:
            if authorization.startswith("Bearer "):
                provided = authorization[7:]
            else:
                provided = authorization

        if not provided or not secrets.compare_digest(provided, settings.gnani_webhook_secret):
            logger.warning("Gnani webhook callback failed secret verification.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Gnani webhook authentication secret.",
            )
        return True

    # If no secret configured and running in live / production mode -> FAIL CLOSED
    if settings.execution_mode == ExecutionMode.AUTHORIZED_EXECUTION:
        logger.error("Gnani webhook receiver invoked in production mode without configured secret.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gnani webhook authentication is unconfigured; failing closed in production mode.",
        )

    # In simulation / development mode, allow callback with warning
    logger.info("Gnani webhook processed in simulation mode (no webhook secret configured).")
    return True
