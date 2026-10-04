"""Tests for AgenticOrg Adapter."""

from aarogya.connectors.registry import ConnectorRegistry
from aarogya.connectors.agenticorg_adapter import AgenticOrgAdapter
from aarogya.config import Settings, ExecutionMode


def test_agenticorg_adapter_isolated_when_no_credentials():
    settings = Settings(
        execution_mode=ExecutionMode.SIMULATION,
        agenticorg_api_key=None,
        agenticorg_grantex_token=None,
    )
    registry = ConnectorRegistry()
    adapter = AgenticOrgAdapter(settings, registry)

    assert adapter.is_connected is False
    summary = adapter.discover_and_sync()
    assert summary["platform_connected"] is False
    assert len(summary["errors"]) > 0
