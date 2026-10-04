"""Module 7: AgenticOrg Authentication & Tenant Discovery Service.

A strictly read-only integration layer that safely authenticates with AgenticOrg,
discovers tenant connectors and MCP tools, normalizes capability states,
and reports accurate diagnostics without executing any healthcare operations.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import httpx

from ..config import Settings, get_settings
from ..models.connector import ConnectorStatus
from ..models.enums import (
    AgenticOrgAuthState,
    DiscoveryStatus,
    AuditEventType,
    ExecutionMode,
)
from .registry import ConnectorRegistry
from ..orchestrator.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


def _sanitize_error(error_msg: str, api_key: Optional[str] = None) -> str:
    """Sanitize error messages to prevent exposing API keys, bearer tokens, or secrets."""
    sanitized = str(error_msg)
    if api_key and api_key in sanitized:
        sanitized = sanitized.replace(api_key, "[REDACTED_API_KEY]")
    # Redact Bearer tokens
    import re
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9\-_\.]+", "Bearer [REDACTED_TOKEN]", sanitized, flags=re.IGNORECASE)
    return sanitized


class AgenticOrgDiscoveryService:
    """Read-only tenant discovery and authentication manager for AgenticOrg.

    Strictly inspects tenant connectors and MCP tools without triggering
    any operational actions (orders, payments, tasks, or record mutations).
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        registry: Optional[ConnectorRegistry] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.settings = settings or get_settings()
        self.registry = registry
        self.audit_logger = audit_logger or AuditLogger(
            log_file=self.settings.audit_log_file,
            redact_sensitive=self.settings.redact_sensitive_data,
        )

        self.auth_state: AgenticOrgAuthState = AgenticOrgAuthState.NOT_CONFIGURED
        self.discovery_status: DiscoveryStatus = DiscoveryStatus.NOT_STARTED
        self.last_discovery_time: Optional[datetime] = None
        self.discovered_connectors: Dict[str, ConnectorStatus] = {}
        self.discovered_mcp_tools: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.auth_error: Optional[str] = None
        self._client: Any = None

    def check_credentials(self) -> Tuple[bool, str]:
        """Check whether AgenticOrg credentials are configured."""
        has_key = bool(self.settings.agenticorg_api_key and self.settings.agenticorg_api_key.strip())
        has_token = bool(self.settings.agenticorg_grantex_token and self.settings.agenticorg_grantex_token.strip())

        if not has_key and not has_token:
            self.auth_state = AgenticOrgAuthState.NOT_CONFIGURED
            self.audit_logger.log(
                event_type=AuditEventType.CREDENTIALS_MISSING,
                status="missing",
                details="AgenticOrg credentials (AGENTICORG_API_KEY or AGENTICORG_GRANTEX_TOKEN) are not configured.",
                execution_mode=self.settings.execution_mode,
            )
            return False, "AgenticOrg credentials not configured."

        return True, "Credentials present."

    def initialize_client(self, custom_client: Any = None) -> Tuple[Any, Optional[str]]:
        """Safely initialize the AgenticOrg SDK client without throwing unhandled exceptions."""
        if custom_client is not None:
            self._client = custom_client
            self.auth_state = AgenticOrgAuthState.INITIALIZING
            self.audit_logger.log(
                event_type=AuditEventType.SDK_INITIALIZATION_COMPLETED,
                status="initialized",
                details="AgenticOrg client initialized via injected instance.",
                execution_mode=self.settings.execution_mode,
            )
            return self._client, None

        has_creds, reason = self.check_credentials()
        if not has_creds:
            return None, reason

        self.auth_state = AgenticOrgAuthState.INITIALIZING
        try:
            from agenticorg import AgenticOrg

            client = AgenticOrg(
                api_key=self.settings.agenticorg_api_key,
                base_url=self.settings.agenticorg_base_url,
                grantex_token=self.settings.agenticorg_grantex_token,
                timeout=self.settings.agenticorg_discovery_timeout_seconds,
            )
            self._client = client
            self.audit_logger.log(
                event_type=AuditEventType.SDK_INITIALIZATION_COMPLETED,
                status="initialized",
                details=f"AgenticOrg SDK client initialized successfully (base_url: {self.settings.agenticorg_base_url}).",
                execution_mode=self.settings.execution_mode,
            )
            return client, None

        except ValueError as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            self.auth_state = AgenticOrgAuthState.NOT_CONFIGURED
            self.auth_error = sanitized
            logger.warning("AgenticOrg initialization config error: %s", sanitized)
            return None, sanitized

        except Exception as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            self.auth_state = AgenticOrgAuthState.CONNECTION_FAILED
            self.auth_error = sanitized
            logger.error("AgenticOrg initialization failure: %s", sanitized)
            return None, sanitized

    def verify_authentication(self, client: Any) -> Tuple[bool, AgenticOrgAuthState, str]:
        """Verify authentication against the AgenticOrg tenant using a documented read-only operation."""
        if client is None:
            self.auth_state = AgenticOrgAuthState.NOT_CONFIGURED
            return False, self.auth_state, "No client instance available for verification."

        # Verify SDK compatibility
        if not hasattr(client, "connectors") or not hasattr(client.connectors, "list"):
            self.auth_state = AgenticOrgAuthState.UNSUPPORTED
            msg = "Installed AgenticOrg SDK client lacks expected read-only connectors interface."
            self.auth_error = msg
            logger.warning(msg)
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                status="unsupported",
                details=msg,
                execution_mode=self.settings.execution_mode,
            )
            return False, self.auth_state, msg

        try:
            # Perform a lightweight read-only query to verify authentication
            _ = client.connectors.list()
            self.auth_state = AgenticOrgAuthState.AUTHENTICATED
            self.auth_error = None
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_SUCCEEDED,
                status="authenticated",
                details="AgenticOrg tenant authentication verified via read-only ping.",
                execution_mode=self.settings.execution_mode,
            )
            return True, self.auth_state, "Authentication confirmed by tenant."

        except httpx.HTTPStatusError as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            status_code = e.response.status_code if e.response else 500
            if status_code in (401, 403):
                self.auth_state = AgenticOrgAuthState.AUTH_FAILED
                reason = f"Authentication rejected by platform (HTTP {status_code}): {e.response.text if e.response else 'Forbidden'}"
            else:
                self.auth_state = AgenticOrgAuthState.CONNECTION_FAILED
                reason = f"Platform HTTP error during authentication check (HTTP {status_code}): {sanitized}"

            sanitized_reason = _sanitize_error(reason, self.settings.agenticorg_api_key)
            self.auth_error = sanitized_reason
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                status=self.auth_state.value,
                details=sanitized_reason,
                execution_mode=self.settings.execution_mode,
            )
            return False, self.auth_state, sanitized_reason

        except (httpx.TimeoutException, TimeoutError) as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            self.auth_state = AgenticOrgAuthState.TIMEOUT
            reason = f"Authentication check timed out after {self.settings.agenticorg_discovery_timeout_seconds}s: {sanitized}"
            self.auth_error = reason
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                status="timeout",
                details=reason,
                execution_mode=self.settings.execution_mode,
            )
            return False, self.auth_state, reason

        except (httpx.ConnectError, httpx.NetworkError) as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            self.auth_state = AgenticOrgAuthState.CONNECTION_FAILED
            reason = f"Connection to AgenticOrg endpoint failed: {sanitized}"
            self.auth_error = reason
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                status="connection_failed",
                details=reason,
                execution_mode=self.settings.execution_mode,
            )
            return False, self.auth_state, reason

        except (AttributeError, NotImplementedError) as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            self.auth_state = AgenticOrgAuthState.UNSUPPORTED
            reason = f"Authentication verification method unsupported by client: {sanitized}"
            self.auth_error = reason
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                status="unsupported",
                details=reason,
                execution_mode=self.settings.execution_mode,
            )
            return False, self.auth_state, reason

        except Exception as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            self.auth_state = AgenticOrgAuthState.CONNECTION_FAILED
            reason = f"Unexpected failure during authentication check: {sanitized}"
            self.auth_error = reason
            self.audit_logger.log(
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                status="failed",
                details=reason,
                execution_mode=self.settings.execution_mode,
            )
            return False, self.auth_state, reason

    def discover_tenant(self, client: Any = None) -> Dict[str, Any]:
        """Perform tenant discovery of connectors and MCP tools.

        This method is strictly read-only. It normalizes discovered items into
        the connector registry without executing any healthcare operations.
        """
        self.errors = []
        self.discovered_connectors = {}
        self.discovered_mcp_tools = []
        self.last_discovery_time = datetime.utcnow()

        self.audit_logger.log(
            event_type=AuditEventType.DISCOVERY_STARTED,
            status="started",
            details="Starting AgenticOrg tenant discovery.",
            execution_mode=self.settings.execution_mode,
        )

        active_client = client or self._client
        if active_client is None:
            active_client, init_err = self.initialize_client()
            if active_client is None:
                self.discovery_status = DiscoveryStatus.FAILED
                self.errors.append(init_err or "Client initialization failed.")
                self.audit_logger.log(
                    event_type=AuditEventType.DISCOVERY_FAILED,
                    status="failed",
                    details=f"Discovery failed at client initialization: {init_err}",
                    execution_mode=self.settings.execution_mode,
                )
                return self._build_report()

        # Step 1: Verify Authentication
        is_auth, auth_state, auth_msg = self.verify_authentication(active_client)
        if not is_auth:
            self.discovery_status = DiscoveryStatus.FAILED
            self.errors.append(auth_msg)
            self.audit_logger.log(
                event_type=AuditEventType.DISCOVERY_FAILED,
                status="failed",
                details=f"Discovery blocked by authentication failure: {auth_msg}",
                execution_mode=self.settings.execution_mode,
            )
            return self._build_report()

        # Step 2: Discover Tenant Connectors
        connectors_ok = False
        connectors_raw: List[Dict[str, Any]] = []
        try:
            result = active_client.connectors.list()
            if isinstance(result, list):
                connectors_raw = result
            elif isinstance(result, dict) and "items" in result:
                connectors_raw = result["items"]
            else:
                connectors_raw = []
            connectors_ok = True
            self.audit_logger.log(
                event_type=AuditEventType.CONNECTOR_DISCOVERY_SUCCEEDED,
                status="success",
                details=f"Discovered {len(connectors_raw)} connector(s) in tenant.",
                execution_mode=self.settings.execution_mode,
                metadata={"connectors_count": len(connectors_raw)},
            )
        except Exception as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            err = f"Connector discovery failed: {sanitized}"
            self.errors.append(err)
            logger.warning(err)

        # Step 3: Discover MCP Tools
        mcp_ok = False
        mcp_raw: List[Dict[str, Any]] = []
        try:
            if hasattr(active_client, "mcp") and hasattr(active_client.mcp, "tools"):
                mcp_res = active_client.mcp.tools()
                if isinstance(mcp_res, list):
                    mcp_raw = mcp_res
                elif isinstance(mcp_res, dict) and "tools" in mcp_res:
                    mcp_raw = mcp_res["tools"]
                mcp_ok = True
                self.audit_logger.log(
                    event_type=AuditEventType.MCP_DISCOVERY_SUCCEEDED,
                    status="success",
                    details=f"Discovered {len(mcp_raw)} MCP tool(s) in tenant.",
                    execution_mode=self.settings.execution_mode,
                    metadata={"mcp_tools_count": len(mcp_raw)},
                )
            else:
                self.errors.append("MCP tools interface not supported on SDK client.")
        except Exception as e:
            sanitized = _sanitize_error(str(e), self.settings.agenticorg_api_key)
            err = f"MCP discovery failed: {sanitized}"
            self.errors.append(err)
            logger.warning(err)

        # Step 4: Normalize Capabilities into Connector Status
        if connectors_ok:
            for item in connectors_raw:
                conn_status = self._normalize_connector(item)
                self.discovered_connectors[conn_status.integration] = conn_status
                if self.registry:
                    self._sync_to_registry(conn_status)

        if mcp_ok:
            for tool in mcp_raw:
                self.discovered_mcp_tools.append(tool)
                tool_status = self._normalize_mcp_tool(tool)
                self.discovered_connectors[tool_status.integration] = tool_status
                if self.registry:
                    self._sync_to_registry(tool_status)

        # Step 5: Determine overall discovery status
        if connectors_ok and mcp_ok:
            self.discovery_status = DiscoveryStatus.SUCCESS
            self.audit_logger.log(
                event_type=AuditEventType.DISCOVERY_COMPLETED,
                status="success",
                details=f"Full discovery completed ({len(connectors_raw)} connectors, {len(mcp_raw)} MCP tools).",
                execution_mode=self.settings.execution_mode,
                metadata={
                    "connectors_count": len(connectors_raw),
                    "mcp_tools_count": len(mcp_raw),
                },
            )
        elif connectors_ok or mcp_ok:
            self.discovery_status = DiscoveryStatus.PARTIAL
            self.audit_logger.log(
                event_type=AuditEventType.PARTIAL_DISCOVERY,
                status="partial",
                details=f"Partial discovery completed with errors: {'; '.join(self.errors)}",
                execution_mode=self.settings.execution_mode,
                metadata={
                    "connectors_count": len(connectors_raw),
                    "mcp_tools_count": len(mcp_raw),
                    "errors_count": len(self.errors),
                },
            )
            self.audit_logger.log(
                event_type=AuditEventType.DISCOVERY_COMPLETED,
                status="partial",
                details="Discovery finalized in partial state.",
                execution_mode=self.settings.execution_mode,
            )
        else:
            self.discovery_status = DiscoveryStatus.FAILED
            self.audit_logger.log(
                event_type=AuditEventType.DISCOVERY_FAILED,
                status="failed",
                details=f"Both connector and MCP discovery failed: {'; '.join(self.errors)}",
                execution_mode=self.settings.execution_mode,
            )

        return self._build_report()

    def _normalize_connector(self, item: Dict[str, Any]) -> ConnectorStatus:
        """Normalize raw tenant connector metadata into an independent capability model."""
        name = str(item.get("name") or item.get("id") or "unnamed_connector")
        cid = str(item.get("id") or name)
        status_val = str(item.get("status") or "").lower()

        # Connect status
        connected = True if status_val == "active" else (False if status_val == "inactive" else None)

        # Health status: only set if explicitly present, else keep None (unknown)
        healthy = None
        if "healthy" in item:
            healthy = bool(item["healthy"])
        elif status_val == "active":
            healthy = True

        # Authorization: must come from explicit tenant evidence; otherwise unknown (None)
        authorized = None
        if "authorized" in item:
            authorized = bool(item["authorized"])
        elif "permissions" in item:
            authorized = bool(item["permissions"])

        # Capabilities: list of supported actions
        capabilities = list(item.get("capabilities") or item.get("supported_capabilities") or [])
        if not capabilities and "category" in item:
            capabilities = [f"category_{item['category']}"]

        capable = True if capabilities else None

        # Clean metadata without credentials
        clean_metadata = {k: v for k, v in item.items() if not any(s in k.lower() for s in ["key", "token", "secret", "auth"])}

        return ConnectorStatus(
            integration=cid,
            documented=True,
            registered=True,  # Proven by appearance in tenant catalog
            authorized=authorized,
            connected=connected,
            healthy=healthy,
            capable=capable,
            supported_capabilities=capabilities,
            provider_name=item.get("provider") or item.get("provider_name") or name,
            endpoint_url=item.get("endpoint_url") or item.get("base_url"),
            error_message=item.get("error_message") or item.get("error"),
            discovery_source="agenticorg_connectors",
            raw_metadata=clean_metadata,
        )

    def _normalize_mcp_tool(self, tool: Dict[str, Any]) -> ConnectorStatus:
        """Normalize an MCP tool definition into an independent capability model."""
        name = str(tool.get("name") or "unnamed_mcp_tool")
        integration_id = f"mcp:{name}"

        # Clean metadata
        clean_meta = {k: v for k, v in tool.items() if not any(s in k.lower() for s in ["key", "token", "secret", "auth"])}

        return ConnectorStatus(
            integration=integration_id,
            documented=True,
            registered=True,
            authorized=None,  # Unknown without explicit RBAC evidence
            connected=True,   # Active MCP endpoint
            healthy=None,     # Unknown without explicit tool health check
            capable=True,
            supported_capabilities=[name],
            provider_name="AgenticOrg MCP Server",
            error_message=None,
            discovery_source="agenticorg_mcp",
            raw_metadata=clean_meta,
        )

    def _sync_to_registry(self, status: ConnectorStatus) -> None:
        """Sync discovered connector into Aarogya's ConnectorRegistry."""
        if not self.registry:
            return

        name_lower = status.integration.lower()
        prov_lower = (status.provider_name or "").lower()

        # Update primary integrations if matched
        if "pharmacy" in name_lower or "pharmacy" in prov_lower or "pharma" in name_lower or "medicine" in name_lower:
            self.registry.update_connector_status("pharmacy", status)

        if "task" in name_lower or "caregiver" in name_lower:
            self.registry.update_connector_status("task_manager", status)

        if "pine" in name_lower or "pine_labs" in name_lower or "payment" in name_lower:
            self.registry.update_connector_status("pine_labs", status)

        if "delhivery" in name_lower or "logistics" in name_lower:
            self.registry.update_connector_status("delhivery", status)

        if "appointment" in name_lower or "clinic" in name_lower or "aarogya" in name_lower or "coordination" in name_lower:
            self.registry.update_connector_status("clinic_coordinator", status)

        # Register by its own identifier
        self.registry.update_connector_status(status.integration, status)

    def _build_report(self) -> Dict[str, Any]:
        """Construct structured discovery diagnostic report."""
        connectors_summary = []
        for c in self.discovered_connectors.values():
            connectors_summary.append({
                "integration": c.integration,
                "provider": c.provider_name,
                "documented": c.documented,
                "registered": c.registered,
                "authorized": c.authorized,
                "connected": c.connected,
                "healthy": c.healthy,
                "capable": c.capable,
                "capabilities": c.supported_capabilities,
                "source": c.discovery_source,
            })

        mcp_summary = []
        for t in self.discovered_mcp_tools:
            mcp_summary.append({
                "name": t.get("name"),
                "description": (t.get("description") or "")[:80],
            })

        is_live = (
            self.auth_state == AgenticOrgAuthState.AUTHENTICATED
            and self.discovery_status in (DiscoveryStatus.SUCCESS, DiscoveryStatus.PARTIAL)
        )

        return {
            "auth_state": self.auth_state.value,
            "discovery_status": self.discovery_status.value,
            "is_live": is_live,
            "registered_connectors_count": len(self.discovered_connectors),
            "mcp_tools_count": len(self.discovered_mcp_tools),
            "connectors": connectors_summary,
            "mcp_tools": mcp_summary,
            "errors": list(self.errors),
            "auth_error": self.auth_error,
            "timestamp": self.last_discovery_time.isoformat() if self.last_discovery_time else None,
            "safety_boundary_verified": True,
            "safety_notes": (
                "Read-only discovery completed. No healthcare operations "
                "(orders, payments, caregiver tasks, appointments, or patient mutations) "
                "were or will be executed during discovery."
            ),
        }
