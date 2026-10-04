"""Module 12: End-to-End Healthcare Coordination Evaluation Package.

Exports models, catalog, reusable assertions, evaluation runner, and reporting.
"""

from .scenario_models import (
    EvaluationStatus,
    AssertionResult,
    ScenarioContext,
    ScenarioResult,
    EvaluationReport,
)
from .scenario_catalog import (
    SCENARIOS,
    get_scenario,
    list_all_scenarios,
)
from .assertions import (
    assert_patient_resolved,
    assert_authorization_enforced,
    assert_no_unauthorized_disclosure,
    assert_capability_verified,
    assert_hitl_approval_required,
    assert_hitl_binding_integrity,
    assert_no_live_execution,
    assert_no_fabricated_data,
    assert_idempotency_enforced,
    assert_uncertain_outcome_requires_verification,
    assert_notification_authorized,
    assert_emergency_safety_routed,
    assert_family_health_brain_unchanged,
    assert_audit_records_persisted,
)
from .evaluation_runner import EvaluationRunner, EvaluationEnvironment
from .reporting import format_evaluation_report, format_scenario_list

__all__ = [
    "EvaluationStatus",
    "AssertionResult",
    "ScenarioContext",
    "ScenarioResult",
    "EvaluationReport",
    "SCENARIOS",
    "get_scenario",
    "list_all_scenarios",
    "EvaluationRunner",
    "EvaluationEnvironment",
    "format_evaluation_report",
    "format_scenario_list",
    "assert_patient_resolved",
    "assert_authorization_enforced",
    "assert_no_unauthorized_disclosure",
    "assert_capability_verified",
    "assert_hitl_approval_required",
    "assert_hitl_binding_integrity",
    "assert_no_live_execution",
    "assert_no_fabricated_data",
    "assert_idempotency_enforced",
    "assert_uncertain_outcome_requires_verification",
    "assert_notification_authorized",
    "assert_emergency_safety_routed",
    "assert_family_health_brain_unchanged",
    "assert_audit_records_persisted",
]
