"""Connector, tool discovery, and capability models."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ConnectorCapability(BaseModel):
    """Specific operational capability supported by a connector."""
    name: str  # e.g., "check_medicine_availability", "create_caregiver_task"
    description: str
    read_only: bool = True
    consequential: bool = False
    requires_approval: bool = False


class ConnectorStatus(BaseModel):
    """Granular state of an integration or connector."""
    integration: str  # e.g., "pharmacy", "task_manager", "pine_labs", "delhivery", "mcp:tool_name"
    documented: bool = True
    registered: bool = False
    authorized: Optional[bool] = None
    connected: Optional[bool] = None
    healthy: Optional[bool] = None
    capable: Optional[bool] = None
    supported_capabilities: List[str] = Field(default_factory=list)
    endpoint_url: Optional[str] = None
    provider_name: Optional[str] = None
    last_health_check: Optional[str] = None
    error_message: Optional[str] = None
    discovery_source: Optional[str] = None  # e.g., "agenticorg_connectors", "agenticorg_mcp", "static_catalog"
    raw_metadata: Optional[Dict[str, Any]] = None


from datetime import datetime
import uuid
from .enums import HealthcareDomain, CapabilityPolicyDecision, DiscoveryStatus


class CapabilityCheckResult(BaseModel):
    """Result of checking whether a requested capability is actually executable."""
    integration: str
    registered: bool
    authorized: Optional[bool] = None
    healthy: Optional[bool] = None
    capable: Optional[bool] = None
    required_capability: str
    available: bool
    reason: str
    is_simulation: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NormalizedCapability(BaseModel):
    """Normalized internal representation of a tenant connector or MCP tool capability."""
    capability_id: str                      # Stable identifier (e.g., 'conn:apollo_01', 'mcp:check_pharmacy_inventory')
    source_platform: str = "agenticorg"     # "agenticorg", "local", "partner"
    tenant_connector_id: Optional[str] = None
    mcp_tool_id: Optional[str] = None
    display_name: str
    description: str = ""
    domain: HealthcareDomain = HealthcareDomain.UNKNOWN
    category: Optional[str] = None
    supported_operations: List[str] = Field(default_factory=list)
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    discovery_timestamp: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    source_metadata_version: Optional[str] = None

    # Independent states: None indicates unknown
    documented: bool = True
    registered: bool = False
    authorized: Optional[bool] = None
    connected: Optional[bool] = None
    healthy: Optional[bool] = None
    capable: Optional[bool] = None
    is_verified_healthcare_partner: bool = False
    is_stale: bool = False
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class SyncHistoryRecord(BaseModel):
    """Immutable audit record of a capability synchronization cycle."""
    sync_id: str = Field(default_factory=lambda: f"sync_{uuid.uuid4().hex[:10]}")
    started_at: datetime
    completed_at: datetime
    discovery_source: str
    connector_count: int = 0
    mcp_tool_count: int = 0
    added_capabilities: List[str] = Field(default_factory=list)
    updated_capabilities: List[str] = Field(default_factory=list)
    stale_capabilities: List[str] = Field(default_factory=list)
    removed_capabilities: List[str] = Field(default_factory=list)
    partial_failures: List[str] = Field(default_factory=list)
    sanitized_errors: List[str] = Field(default_factory=list)
    status: DiscoveryStatus = DiscoveryStatus.SUCCESS


class CapabilityPolicyEvaluation(BaseModel):
    """Outcome of evaluating capability operational readiness against policy."""
    capability_id: str
    workflow: str
    required_operation: str
    decision: CapabilityPolicyDecision
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
