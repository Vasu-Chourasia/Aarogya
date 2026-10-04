"""Tests for Module 2: Tool and Connector Discovery & Capability Registry."""

from aarogya.connectors.registry import ConnectorRegistry
from aarogya.models.connector import ConnectorStatus
from aarogya.models.enums import ExecutionMode


def test_unregistered_connector_capability_check():
    # Production / non-simulation mode: unregistered pharmacy connector
    registry = ConnectorRegistry(execution_mode=ExecutionMode.AUTHORIZED_EXECUTION)
    
    result = registry.check_capability("pharmacy", "check_medicine_availability")
    
    assert result.available is False
    assert result.registered is False
    assert result.authorized is False
    assert result.healthy is False
    assert "No configured pharmacy integration" in result.reason


def test_distinguishes_registered_but_unhealthy_connector():
    registry = ConnectorRegistry(execution_mode=ExecutionMode.AUTHORIZED_EXECUTION)
    
    # Register connector but mark it unhealthy/disconnected
    registry.update_connector_status(
        "pharmacy",
        ConnectorStatus(
            integration="pharmacy",
            documented=True,
            registered=True,
            authorized=True,
            connected=False,
            healthy=False,
            supported_capabilities=["check_medicine_availability"],
            error_message="Connection refused on port 8080",
        )
    )

    result = registry.check_capability("pharmacy", "check_medicine_availability")
    assert result.available is False
    assert result.registered is True
    assert result.authorized is True
    assert result.healthy is False
    assert "unreachable or unhealthy" in result.reason


def test_simulation_mode_explicitly_labeled():
    registry = ConnectorRegistry(execution_mode=ExecutionMode.SIMULATION)
    result = registry.check_capability("pharmacy", "check_medicine_availability", allow_simulation=True)
    
    assert result.available is True
    assert result.is_simulation is True
    assert "simulation mode" in result.reason.lower()
