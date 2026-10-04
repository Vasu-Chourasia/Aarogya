"""Module 13: Competition Demonstration & Technical Readiness Package.

Exports demo scenarios, runner, reporting formatters, truth matrices,
and readiness assessments.
"""

from .demo_scenarios import (
    DemoScenarioKey,
    DemoScenarioDefinition,
    DEMO_SCENARIOS,
    get_demo_scenario,
    list_demo_scenarios,
)
from .demo_runner import (
    CompetitionDemoOrchestrator,
    DemoExecutionResult,
    DemoWorkflowStep,
)
from .readiness_assessment import (
    CapabilityStatus,
    CapabilityEntry,
    CAPABILITY_TRUTH_MATRIX,
    TruthfulEvaluationMetrics,
    TechnicalReadinessCategory,
    get_technical_readiness_assessment,
)
from .demo_report import (
    format_demo_list,
    format_single_demo_result,
    format_all_demo_results,
    format_capability_truth_matrix,
    format_readiness_report,
)

__all__ = [
    "DemoScenarioKey",
    "DemoScenarioDefinition",
    "DEMO_SCENARIOS",
    "get_demo_scenario",
    "list_demo_scenarios",
    "CompetitionDemoOrchestrator",
    "DemoExecutionResult",
    "DemoWorkflowStep",
    "CapabilityStatus",
    "CapabilityEntry",
    "CAPABILITY_TRUTH_MATRIX",
    "TruthfulEvaluationMetrics",
    "TechnicalReadinessCategory",
    "get_technical_readiness_assessment",
    "format_demo_list",
    "format_single_demo_result",
    "format_all_demo_results",
    "format_capability_truth_matrix",
    "format_readiness_report",
]
