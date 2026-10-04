"""Module 12: End-to-End Evaluation Scenario Models.

Defines strongly typed Pydantic models for evaluation scenarios,
reusable assertion outcomes, scenario run contexts, and aggregate reports.
"""

from enum import Enum
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class EvaluationStatus(str, Enum):
    """Evaluation status conforming to Section 6 distinctions."""
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssertionResult(BaseModel):
    """Result of a single atomic evaluation assertion."""
    name: str
    status: EvaluationStatus
    message: str
    details: Optional[Dict[str, Any]] = None


class ScenarioContext(BaseModel):
    """Structured context defining a test scenario input and expected invariants."""
    scenario_id: str
    title: str
    description: str
    request_text: str
    user_id: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_relationship: Optional[str] = None
    medicine_name: Optional[str] = None
    quantity: Optional[int] = None
    idempotency_key: Optional[str] = None
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    expected_safety: str
    expected_execution: str
    expected_outcome: str


class ScenarioResult(BaseModel):
    """Outcome of running a single scenario through the full Aarogya architecture."""
    scenario_id: str
    title: str
    description: str
    status: EvaluationStatus
    assertions: List[AssertionResult] = Field(default_factory=list)
    agent_response: Optional[Dict[str, Any]] = None
    gateway_result: Optional[Dict[str, Any]] = None
    safety_violations: List[str] = Field(default_factory=list)
    audit_events_count: int = 0
    execution_mode: str = "SIMULATION"
    provider_mode: str = "mock"
    live_execution_enabled: bool = False
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    """Comprehensive evaluation report summarizing results across all scenarios."""
    total_scenarios: int
    passed: int
    failed: int
    blocked: int
    not_applicable: int
    scenario_results: List[ScenarioResult]
    summary: str
    timestamp: datetime
    execution_mode: str = "SIMULATION"
    provider_mode: str = "mock"
    live_execution_enabled: bool = False

    @property
    def pass_rate(self) -> float:
        """Truthful pass rate computation. Blocked scenarios are NOT counted as completed."""
        return (self.passed / self.total_scenarios * 100.0) if self.total_scenarios > 0 else 0.0
