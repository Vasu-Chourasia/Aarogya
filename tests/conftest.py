"""Test configuration and fixtures."""

import sys
import os
import pytest

# Ensure aarogya package is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aarogya.brain.family_health_brain import FamilyHealthBrain
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.connectors.pharmacy_connector import MockDirectPharmacyConnector
from aarogya.connectors.task_connector import LocalDevelopmentTaskBackend
from aarogya.policy.authorization_engine import PolicyAuthorizationEngine
from aarogya.workflows.approval_manager import ApprovalManager
from aarogya.workflows.verification import OutcomeVerificationService
from aarogya.orchestrator.agent import AarogyaAgent
from aarogya.config import Settings, ExecutionMode


@pytest.fixture
def brain():
    return FamilyHealthBrain(seed_fictional_data=True)


@pytest.fixture
def connector_registry():
    return ConnectorRegistry(execution_mode=ExecutionMode.SIMULATION)


@pytest.fixture
def mock_pharmacy():
    return MockDirectPharmacyConnector()


@pytest.fixture
def task_backend():
    return LocalDevelopmentTaskBackend()


@pytest.fixture
def policy_engine(brain):
    return PolicyAuthorizationEngine(brain)


@pytest.fixture
def approval_manager():
    return ApprovalManager()


@pytest.fixture
def verification_service():
    return OutcomeVerificationService(ExecutionMode.SIMULATION)


@pytest.fixture
def simulation_agent(brain, connector_registry, mock_pharmacy, task_backend):
    settings = Settings(execution_mode=ExecutionMode.SIMULATION)
    return AarogyaAgent(
        settings=settings,
        brain=brain,
        connector_registry=connector_registry,
        pharmacy_connector=mock_pharmacy,
        task_backend=task_backend,
    )
