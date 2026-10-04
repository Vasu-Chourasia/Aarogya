"""AgenticOrg Platform Adapter.

Wraps the AgenticOrg Python SDK to discover registered connectors, MCP tools,
and agent fleet status, bridging them into the Aarogya ConnectorRegistry.
Integrates Module 7 AgenticOrgDiscoveryService for robust read-only authentication
and tenant capability discovery.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
from ..config import Settings, ExecutionMode
from ..models.connector import ConnectorStatus
from ..models.enums import AgenticOrgAuthState
from .registry import ConnectorRegistry
from .agenticorg_discovery import AgenticOrgDiscoveryService

logger = logging.getLogger(__name__)


class AgenticOrgAdapter:
    """Safely interfaces with AgenticOrg Enterprise Fleet."""

    def __init__(
        self,
        settings: Settings,
        registry: ConnectorRegistry,
        discovery_service: Optional[AgenticOrgDiscoveryService] = None,
    ):
        self.settings = settings
        self.registry = registry
        self.discovery_service = discovery_service or AgenticOrgDiscoveryService(
            settings=settings,
            registry=registry,
        )
        self._client = None
        self._is_connected = False
        self._init_client()

    def _init_client(self):
        """Attempt initialization of AgenticOrg SDK client using discovery service."""
        client, err = self.discovery_service.initialize_client()
        if client is not None:
            self._client = client
            self._is_connected = True
        else:
            self._client = None
            self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def discover_and_sync(self) -> Dict[str, Any]:
        """Query platform API to discover active connectors and MCP tools.

        Does not assume capabilities; records actual discovery results.
        Enforces read-only operations and prevents executing any tools.
        """
        discovery_report = self.discovery_service.discover_tenant(self._client)

        summary: Dict[str, Any] = {
            "platform_connected": discovery_report.get("is_live", False),
            "auth_state": discovery_report.get("auth_state"),
            "discovery_status": discovery_report.get("discovery_status"),
            "registered_connectors_count": discovery_report.get("registered_connectors_count", 0),
            "mcp_tools_count": discovery_report.get("mcp_tools_count", 0),
            "aarogya_agent_found": False,
            "errors": list(discovery_report.get("errors", [])),
            "safety_boundary_verified": discovery_report.get("safety_boundary_verified", True),
        }

        # Inspect Aarogya Agent definition if authenticated
        if self._client and self.discovery_service.auth_state == AgenticOrgAuthState.AUTHENTICATED:
            try:
                if hasattr(self._client, "agents") and hasattr(self._client.agents, "get"):
                    agent = self._client.agents.get(self.settings.agenticorg_agent_id)
                    if agent:
                        summary["aarogya_agent_found"] = True
                        summary["agent_details"] = agent
            except Exception as e:
                logger.warning("AgenticOrg agent query error: %s", str(e))
                summary["errors"].append(f"Agent get failed: {str(e)}")

        return summary
