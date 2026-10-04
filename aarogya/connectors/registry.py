"""Module 2: Connector Discovery and Capability Registry."""

from typing import Dict, Optional, List, Any
from ..models.connector import (
    ConnectorStatus,
    CapabilityCheckResult,
    ConnectorCapability,
    NormalizedCapability,
    SyncHistoryRecord,
    CapabilityPolicyEvaluation,
)
from ..models.enums import ExecutionMode
from ..config import get_settings
from .capability_synchronizer import CapabilitySynchronizer


class ConnectorRegistry:
    """Capability-checking layer distinguishing platform documentation,
    tenant registration, agent authorization, connection, health, and operational capability.
    """

    def __init__(
        self,
        execution_mode: ExecutionMode = ExecutionMode.SIMULATION,
        synchronizer: Optional[CapabilitySynchronizer] = None,
        capability_repo: Optional[Any] = None,
        sync_history_repo: Optional[Any] = None,
    ):
        self.execution_mode = execution_mode
        self._connectors: Dict[str, ConnectorStatus] = {}
        self.capability_repo = capability_repo
        self.sync_history_repo = sync_history_repo
        self._synchronizer = synchronizer or CapabilitySynchronizer(
            settings=get_settings(),
            capability_repo=capability_repo,
            sync_history_repo=sync_history_repo,
        )
        self._register_default_catalog()

    @property
    def synchronizer(self) -> CapabilitySynchronizer:
        """Access the underlying capability synchronization engine."""
        return self._synchronizer

    def _register_default_catalog(self):
        """Register documented platform connectors with their baseline states."""
        # Pharmacy connector (Direct Pharmacy API - not ONDC)
        self._connectors["pharmacy"] = ConnectorStatus(
            integration="pharmacy",
            documented=True,
            registered=False,  # Unregistered by default until tenant configured
            authorized=False,
            connected=False,
            healthy=False,
            supported_capabilities=["check_medicine_availability", "reserve_inventory"],
            provider_name="Apollo/MedPlus Direct Pharmacy API",
            error_message="No configured pharmacy integration in tenant",
        )
        
        # Caregiver Task backend connector
        self._connectors["task_manager"] = ConnectorStatus(
            integration="task_manager",
            documented=True,
            registered=False,
            authorized=False,
            connected=False,
            healthy=False,
            supported_capabilities=["create_caregiver_task", "query_caregiver_task", "update_caregiver_task"],
            provider_name="Aarogya Family Task Engine",
            error_message="No configured task-management connector",
        )

        # Pine Labs payment connector
        self._connectors["pine_labs"] = ConnectorStatus(
            integration="pine_labs",
            documented=True,
            registered=False,
            authorized=False,
            connected=False,
            healthy=False,
            supported_capabilities=["initiate_payment", "verify_payment_status"],
            provider_name="Pine Labs Payment Gateway",
            error_message="Pine Labs payment gateway not configured",
        )

        # Delhivery logistics connector
        self._connectors["delhivery"] = ConnectorStatus(
            integration="delhivery",
            documented=True,
            registered=False,
            authorized=False,
            connected=False,
            healthy=False,
            supported_capabilities=["track_delivery", "schedule_pickup"],
            provider_name="Delhivery Logistics",
            error_message="Delhivery logistics integration not configured",
        )

    def update_connector_status(self, integration: str, status: ConnectorStatus):
        """Update or register connector status discovered from platform SDK or environment."""
        self._connectors[integration] = status

    def get_connector_status(self, integration: str) -> Optional[ConnectorStatus]:
        """Retrieve granular state of a connector."""
        return self._connectors.get(integration)

    def check_capability(
        self,
        integration: str,
        required_capability: str,
        allow_simulation: bool = False,
    ) -> CapabilityCheckResult:
        """Evaluate whether a specific operational capability is truly executable.
        
        Enforces strict distinction:
        Documented != Registered != Authorized != Connected != Healthy != Capable.
        """
        conn = self._connectors.get(integration)
        if not conn:
            return CapabilityCheckResult(
                integration=integration,
                registered=False,
                authorized=False,
                healthy=False,
                required_capability=required_capability,
                available=False,
                reason=f"Integration '{integration}' is not documented or recognized by the platform.",
                is_simulation=False,
            )

        # In simulation mode, if explicitly permitted and simulation connector active
        if allow_simulation and self.execution_mode == ExecutionMode.SIMULATION:
            return CapabilityCheckResult(
                integration=integration,
                registered=True,
                authorized=True,
                healthy=True,
                required_capability=required_capability,
                available=True,
                reason="Available under explicit local simulation mode (simulated mock provider).",
                is_simulation=True,
                metadata={"simulation": True},
            )

        # Check documented capability
        if required_capability not in conn.supported_capabilities:
            return CapabilityCheckResult(
                integration=integration,
                registered=conn.registered,
                authorized=conn.authorized,
                healthy=conn.healthy,
                required_capability=required_capability,
                available=False,
                reason=f"Connector '{integration}' does not support required capability '{required_capability}'.",
                is_simulation=False,
            )

        # Check registration
        if not conn.registered:
            return CapabilityCheckResult(
                integration=integration,
                registered=False,
                authorized=False,
                healthy=False,
                required_capability=required_capability,
                available=False,
                reason=conn.error_message or f"No configured {integration} integration",
                is_simulation=False,
            )

        # Check agent authorization
        if not conn.authorized:
            return CapabilityCheckResult(
                integration=integration,
                registered=True,
                authorized=False,
                healthy=False,
                required_capability=required_capability,
                available=False,
                reason=f"Agent Aarogya is not authorized to invoke {integration} tools.",
                is_simulation=False,
            )

        # Check connection & health
        if not conn.connected or not conn.healthy:
            return CapabilityCheckResult(
                integration=integration,
                registered=True,
                authorized=True,
                healthy=False,
                required_capability=required_capability,
                available=False,
                reason=f"{integration.capitalize()} connector is registered but currently unreachable or unhealthy: {conn.error_message or 'Health check failed'}",
                is_simulation=False,
            )

        # Fully executable
        return CapabilityCheckResult(
            integration=integration,
            registered=True,
            authorized=True,
            healthy=True,
            required_capability=required_capability,
            available=True,
            reason=f"Connector '{integration}' is operational and authorized for '{required_capability}'.",
            is_simulation=False,
        )

    def sync_capabilities(
        self,
        discovery_report: Optional[Dict[str, Any]] = None,
        discovery_service: Optional[Any] = None,
    ) -> SyncHistoryRecord:
        """Run capability synchronization and reconcile into internal registry."""
        return self._synchronizer.synchronize(
            discovery_report=discovery_report,
            discovery_service=discovery_service,
        )

    def get_normalized_capability(self, capability_id: str) -> Optional[NormalizedCapability]:
        """Retrieve a normalized capability by ID."""
        cap = self._synchronizer.capabilities.get(capability_id)
        if cap:
            return cap
        if self.capability_repo:
            try:
                return self.capability_repo.get(capability_id)
            except Exception:
                pass
        return None

    def list_normalized_capabilities(self) -> List[NormalizedCapability]:
        """List all normalized capabilities currently in registry."""
        if self.capability_repo:
            try:
                persisted = self.capability_repo.list_all()
                if persisted:
                    return persisted
            except Exception:
                pass
        return list(self._synchronizer.capabilities.values())

    def evaluate_capability_policy(
        self,
        capability_id: str,
        workflow: str,
        required_operation: str,
        healthcare_auth_context: Optional[Dict[str, Any]] = None,
    ) -> CapabilityPolicyEvaluation:
        """Evaluate a registered capability's eligibility for a healthcare workflow."""
        cap = self._synchronizer.capabilities.get(capability_id)
        if not cap:
            from datetime import datetime
            from ..models.enums import CapabilityPolicyDecision
            return CapabilityPolicyEvaluation(
                capability_id=capability_id,
                workflow=workflow,
                required_operation=required_operation,
                decision=CapabilityPolicyDecision.BLOCKED_NOT_REGISTERED,
                reason=f"Capability '{capability_id}' not found in normalized registry.",
                timestamp=datetime.utcnow(),
            )
        return self._synchronizer.evaluate_capability_for_workflow(
            capability=cap,
            workflow=workflow,
            required_operation=required_operation,
            healthcare_auth_context=healthcare_auth_context,
        )

    def get_sync_history(self) -> List[SyncHistoryRecord]:
        """Get history of all synchronization runs."""
        return self._synchronizer.sync_history

