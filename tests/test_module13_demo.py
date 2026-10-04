"""Module 13: Competition Demonstration & Technical Readiness Tests.

Comprehensive 28-point automated test suite verifying competition demonstration
orchestrator, scenario executions, capability truth matrix, truthful outcome
accounting metrics, technical readiness report, and CLI commands.
"""

import os
import pytest
from datetime import datetime
from typing import Dict, Any

from aarogya.config import Settings, ExecutionMode
from aarogya.models.enums import (
    RequestType,
    ExecutionStatus,
    AuditEventType,
    GatewayExecutionStatus,
    HealthcareDomain,
    VerificationStatus,
)
from aarogya.models.request import HealthcareRequest
from aarogya.models.gateway import ExecutionRequest
from aarogya.demo.demo_scenarios import (
    DemoScenarioKey,
    DemoScenarioDefinition,
    DEMO_SCENARIOS,
    get_demo_scenario,
    list_demo_scenarios,
)
from aarogya.demo.demo_runner import (
    CompetitionDemoOrchestrator,
    DemoExecutionResult,
    DemoWorkflowStep,
)
from aarogya.demo.readiness_assessment import (
    CapabilityStatus,
    CapabilityEntry,
    CAPABILITY_TRUTH_MATRIX,
    TruthfulEvaluationMetrics,
    TechnicalReadinessCategory,
    get_technical_readiness_assessment,
)
from aarogya.demo.demo_report import (
    format_demo_list,
    format_single_demo_result,
    format_all_demo_results,
    format_capability_truth_matrix,
    format_readiness_report,
)
from aarogya.cli import main


# ---------------------------------------------------------------------------
# 1. Demo Scenario Discovery & Catalog Tests
# ---------------------------------------------------------------------------

def test_demo_scenario_catalog_loading():
    """Verify all 5 competition demo scenarios are loaded and configured."""
    assert len(DEMO_SCENARIOS) == 5
    required_keys = [
        DemoScenarioKey.FAMILY_MEDICINE,
        DemoScenarioKey.UNAUTHORIZED_ACCESS,
        DemoScenarioKey.EMERGENCY_ROUTING,
        DemoScenarioKey.PROVIDER_FAILURE,
        DemoScenarioKey.UNCERTAIN_OUTCOME,
    ]
    for key in required_keys:
        sc = get_demo_scenario(key.value)
        assert sc is not None
        assert sc.key == key
        assert len(sc.title) > 0
        assert len(sc.narrative) > 0
        assert len(sc.target_problem) > 0
        assert len(sc.user_prompt) > 0
        assert len(sc.expected_workflow_stages) > 0
        assert len(sc.demonstration_highlights) > 0


def test_demo_scenario_list_all():
    """Verify list_demo_scenarios returns exactly 5 scenario definitions."""
    scenarios = list_demo_scenarios()
    assert len(scenarios) == 5
    assert all(isinstance(s, DemoScenarioDefinition) for s in scenarios)


def test_demo_scenario_invalid_key_raises_key_error():
    """Verify requesting an invalid demo scenario raises KeyError with available keys."""
    with pytest.raises(KeyError) as exc:
        get_demo_scenario("non_existent_demo")
    assert "not found" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. Individual Demonstration Executions
# ---------------------------------------------------------------------------

def test_demo_1_family_medicine_coordination(tmp_path):
    """Demo 1: Family medicine refill coordination executes end-to-end safely."""
    db_file = str(tmp_path / "test_demo_1.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.FAMILY_MEDICINE)

    assert isinstance(res, DemoExecutionResult)
    assert res.scenario_key == DemoScenarioKey.FAMILY_MEDICINE
    assert "AWAITING_APPROVAL" in res.final_execution_status
    assert res.approval_status == "PENDING_HUMAN_APPROVAL"
    assert "VERIFIED_SIMULATION" in res.verification_status
    assert len(res.steps) >= 6

    step_titles = [s.title for s in res.steps]
    assert "Caregiver Request Ingestion" in step_titles
    assert "Request Understanding & Entity Extraction" in step_titles
    assert "Patient Resolution & Healthcare Authorization" in step_titles
    assert "Verified Health Brain Context Retrieval" in step_titles
    assert "Direct Pharmacy Capability & Inventory Lookup" in step_titles
    assert "Consequential Action Boundary & HITL Approval" in step_titles
    assert "Caregiver Notification & Durable Audit Record" in step_titles


def test_demo_2_unauthorized_access_containment(tmp_path):
    """Demo 2: Stranger request blocked with zero data disclosure."""
    db_file = str(tmp_path / "test_demo_2.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.UNAUTHORIZED_ACCESS)

    assert res.scenario_key == DemoScenarioKey.UNAUTHORIZED_ACCESS
    assert res.final_execution_status == "BLOCKED_UNAUTHORIZED"
    assert "CONTAINED" in res.verification_status
    assert "BLOCKED_BY_POLICY" in res.safety_decision

    step_titles = [s.title for s in res.steps]
    assert "Healthcare Authorization Evaluation" in step_titles
    assert "Privacy Containment & Zero Tool Invocation" in step_titles
    assert "Redacted Denial Audit Trail" in step_titles


def test_demo_3_emergency_clinical_routing(tmp_path):
    """Demo 3: Acute symptoms routed immediately to emergency services (108/112)."""
    db_file = str(tmp_path / "test_demo_3.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.EMERGENCY_ROUTING)

    assert res.scenario_key == DemoScenarioKey.EMERGENCY_ROUTING
    assert res.final_execution_status == "ROUTED_TO_EMERGENCY"
    assert "EMERGENCY_FAST_PATH" in res.safety_decision
    assert res.approval_status == "NOT_APPLICABLE (Life-Critical Emergency)"

    step_titles = [s.title for s in res.steps]
    assert "Clinical Red-Flag Keyword Interception" in step_titles
    assert "Immediate Emergency Direction & Workflow Bypass" in step_titles
    assert "Disclaimer & Emergency Safety Audit Record" in step_titles


def test_demo_4_pharmacy_provider_timeout_handling(tmp_path):
    """Demo 4: Upstream timeout caught with zero hallucinated inventory or price."""
    db_file = str(tmp_path / "test_demo_4.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.PROVIDER_FAILURE)

    assert res.scenario_key == DemoScenarioKey.PROVIDER_FAILURE
    assert "TIMED_OUT" in res.final_execution_status
    assert "TRUTHFUL_FAILURE" in res.safety_decision
    assert res.approval_status == "NOT_APPLICABLE (Execution Failed)"

    step_titles = [s.title for s in res.steps]
    assert "Gateway Execution & Upstream Timeout Handling" in step_titles
    assert "Anti-Hallucination Safeguard Enforcement" in step_titles
    assert "Failure Audit Logging & User Explanation" in step_titles


def test_demo_5_uncertain_outcome_and_reconciliation(tmp_path):
    """Demo 5: Lost external outcome requires verification and blocks duplicate dispatch."""
    db_file = str(tmp_path / "test_demo_5.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.UNCERTAIN_OUTCOME)

    assert res.scenario_key == DemoScenarioKey.UNCERTAIN_OUTCOME
    assert "REQUIRES_VERIFICATION" in res.final_execution_status
    assert "DUPLICATE_DISPATCH_BLOCKED" in res.safety_decision

    step_titles = [s.title for s in res.steps]
    assert "Idempotent Consequential Request Dispatch" in step_titles
    assert "Post-Dispatch Network Drop Simulation" in step_titles
    assert "Duplicate Dispatch Interception & Policy Gate" in step_titles
    assert "Durable State & Reconciliation Audit Trail" in step_titles


# ---------------------------------------------------------------------------
# 3. Safety Guardrails & Operational Invariants
# ---------------------------------------------------------------------------

def test_no_live_execution_across_all_demos(tmp_path):
    """Verify live real-world execution is disabled across all 5 demo scenarios."""
    db_file = str(tmp_path / "test_safety_live.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    results = orchestrator.run_all()
    for res in results:
        assert "STRICTLY DISABLED" in res.live_execution_status


def test_no_real_orders_or_payments_in_demo_1(tmp_path):
    """Verify Demo 1 refrains from creating real pharmacy orders or payments."""
    db_file = str(tmp_path / "test_no_orders.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.FAMILY_MEDICINE)
    assert res.approval_status == "PENDING_HUMAN_APPROVAL"
    assert "No Real Order Placed" in res.verification_status


def test_no_secret_leakage_in_demo_results(tmp_path):
    """Verify demo steps and evidence do not expose API keys, tokens, or credentials."""
    db_file = str(tmp_path / "test_secrets.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    results = orchestrator.run_all()
    forbidden = ["sk_", "bearer", "api_key", "password", "secret", "grantex_token"]
    for res in results:
        text_repr = str(res.model_dump()).lower()
        for f in forbidden:
            assert f"{f}=" not in text_repr
            assert f"'{f}':" not in text_repr or "redacted" in text_repr


def test_orchestrator_run_all(tmp_path):
    """Verify CompetitionDemoOrchestrator.run_all executes all 5 demos without errors."""
    db_file = str(tmp_path / "test_run_all.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    results = orchestrator.run_all()
    assert len(results) == 5
    assert all(isinstance(r, DemoExecutionResult) for r in results)


# ---------------------------------------------------------------------------
# 4. Capability Truth Matrix & Truthful Accounting Tests
# ---------------------------------------------------------------------------

def test_capability_truth_matrix_has_20_capabilities():
    """Verify capability truth matrix contains all 20 capabilities required by Section 6."""
    assert len(CAPABILITY_TRUTH_MATRIX) == 20
    indices = [c.index for c in CAPABILITY_TRUTH_MATRIX]
    assert indices == list(range(1, 21))


def test_capability_truth_matrix_live_verification_strictly_zero():
    """Verify that zero capabilities are marked as live production verified."""
    live_verified_count = sum(1 for c in CAPABILITY_TRUTH_MATRIX if c.live_verified)
    assert live_verified_count == 0


def test_truthful_accounting_metrics_distinguish_rates():
    """Verify truthful accounting distinguishes evaluation pass rate from workflow completion."""
    metrics = TruthfulEvaluationMetrics()

    # Scenario Evaluation Pass Rate includes safety containment blocks
    assert metrics.scenario_evaluation_pass_rate_pct == 100.0
    assert metrics.scenario_evaluation_pass_rate_num == 10
    assert metrics.scenario_evaluation_pass_rate_den == 10

    # Safety Containment Rate is strictly for unsafe scenarios
    assert metrics.safety_containment_rate_pct == 100.0
    assert metrics.safety_containment_rate_num == 3
    assert metrics.safety_containment_rate_den == 3

    # Completed Healthcare Workflow Rate excludes blocked requests
    assert metrics.completed_healthcare_workflow_rate_pct == 70.0
    assert metrics.completed_healthcare_workflow_rate_num == 7
    assert metrics.completed_healthcare_workflow_rate_den == 10

    # Completed rate cannot equal 100.0% when requests were blocked
    assert metrics.completed_healthcare_workflow_rate_pct != metrics.scenario_evaluation_pass_rate_pct

    # Live integration verified count is zero
    assert metrics.live_integrations_verified_num == 0
    assert metrics.live_integrations_verified_pct == 0.0


def test_strict_completion_and_demo_accounting_reconciliation():
    """Verify Module 14 metric reconciliation: strict completion and demo accounting."""
    metrics = TruthfulEvaluationMetrics()

    # Strict completion excludes pending approvals (2), timeouts (1), blocked (3), and unknown (1)
    assert metrics.strict_completed_workflow_rate_num == 3
    assert metrics.strict_completed_workflow_rate_den == 10
    assert metrics.strict_completed_workflow_rate_pct == 30.0

    # Module 13 5-scenario demo specific metrics
    assert metrics.demo_evaluation_pass_rate_pct == 100.0
    assert metrics.demo_evaluation_pass_rate_num == 5
    assert metrics.demo_evaluation_pass_rate_den == 5
    assert metrics.demo_safety_containment_rate_pct == 100.0
    assert metrics.demo_safety_containment_rate_num == 1
    assert metrics.demo_safety_containment_rate_den == 1

    # Demo completed rate strictly counts verified complete (Demo 3 emergency triage)
    assert metrics.demo_completed_workflow_rate_num == 1
    assert metrics.demo_completed_workflow_rate_den == 5
    assert metrics.demo_completed_workflow_rate_pct == 20.0
    assert metrics.demo_pending_approval_count == 1
    assert metrics.demo_uncertain_outcome_count == 1


def test_technical_readiness_assessment_covers_5_domains():
    """Verify technical readiness report covers Architecture, Reliability, Security, Safety, Deployment."""
    assessment = get_technical_readiness_assessment()
    assert len(assessment) == 5
    domains = [c.domain for c in assessment]
    assert any("Architecture" in d for d in domains)
    assert any("Reliability" in d for d in domains)
    assert any("Security" in d for d in domains)
    assert any("Healthcare Safety" in d for d in domains)
    assert any("Deployment" in d for d in domains)


def test_technical_readiness_items_have_gaps_and_actions():
    """Verify all readiness assessment items provide evidence, known gap, and next action."""
    assessment = get_technical_readiness_assessment()
    for cat in assessment:
        for item in cat.items:
            assert len(item["item"]) > 0
            assert len(item["evidence"]) > 0
            assert len(item["status"]) > 0
            assert len(item["known_gap"]) > 0
            assert len(item["required_action"]) > 0


# ---------------------------------------------------------------------------
# 5. Reporting Formatters & CLI Tests
# ---------------------------------------------------------------------------

def test_format_demo_list():
    """Verify format_demo_list outputs structured ASCII catalog."""
    scenarios = list_demo_scenarios()
    output = format_demo_list(scenarios)
    assert "AAROGYA -- COMPETITION DEMONSTRATION CATALOG (MODULE 13)" in output
    assert "FAMILY-MEDICINE" in output
    assert "UNAUTHORIZED-ACCESS" in output
    assert "EMERGENCY-ROUTING" in output
    assert "PROVIDER-FAILURE" in output
    assert "UNCERTAIN-OUTCOME" in output


def test_format_single_demo_result(tmp_path):
    """Verify format_single_demo_result produces clean, readable display."""
    db_file = str(tmp_path / "test_format_single.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.FAMILY_MEDICINE)
    output = format_single_demo_result(res)
    assert "AAROGYA LIVE DEMONSTRATION: DEMO 1" in output
    assert "END-TO-END WORKFLOW EXECUTION STEPS:" in output
    assert "SYSTEM STATUS & SAFETY BOUNDARIES:" in output
    assert "DEMONSTRATION HIGHLIGHTS:" in output


def test_format_all_demo_results(tmp_path):
    """Verify format_all_demo_results compiles all 5 demo outputs."""
    db_file = str(tmp_path / "test_format_all.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    results = orchestrator.run_all()
    output = format_all_demo_results(results)
    assert "AAROGYA -- COMPLETE COMPETITION DEMO SUITE (5 SCENARIOS)" in output
    assert "SUMMARY OF COMPETITION DEMO RUN:" in output
    assert "Total Scenarios Executed:  5" in output


def test_format_capability_truth_matrix():
    """Verify format_capability_truth_matrix formats 20 capabilities and metrics."""
    output = format_capability_truth_matrix()
    assert "AAROGYA -- CAPABILITY TRUTH MATRIX (SECTION 6 & 6A)" in output
    assert "Family onboarding" in output
    assert "AgenticOrg connector discovery" in output
    assert "TRUTHFUL OUTCOME ACCOUNTING METRICS (SECTION 6A):" in output
    assert "70.0% (7/10)" in output


def test_format_readiness_report():
    """Verify format_readiness_report renders all domains and honest disclosure."""
    output = format_readiness_report()
    assert "AAROGYA -- TECHNICAL READINESS & COMPETITION ASSESSMENT REPORT" in output
    assert "ARCHITECTURE" in output
    assert "HEALTHCARE SAFETY" in output
    assert "COMPETITION READINESS SUMMARY & HONEST DISCLOSURE:" in output


def test_cli_demo_list(capsys):
    """Verify CLI demo-list command returns 0 and prints catalog."""
    code = main(["demo-list"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AAROGYA -- COMPETITION DEMONSTRATION CATALOG (MODULE 13)" in captured.out
    assert "FAMILY-MEDICINE" in captured.out


def test_cli_demo_run_single(capsys):
    """Verify CLI demo-run --scenario family-medicine --simulated runs successfully."""
    code = main(["demo-run", "--scenario", "family-medicine", "--simulated"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AAROGYA LIVE DEMONSTRATION: DEMO 1" in captured.out
    assert "AWAITING_APPROVAL" in captured.out


def test_cli_demo_run_all(capsys):
    """Verify CLI demo-run --all --simulated executes all 5 demos."""
    code = main(["demo-run", "--all", "--simulated"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AAROGYA -- COMPLETE COMPETITION DEMO SUITE (5 SCENARIOS)" in captured.out
    assert "Total Scenarios Executed:  5" in captured.out


def test_cli_readiness_report(capsys):
    """Verify CLI readiness-report prints capability matrix and readiness report."""
    code = main(["readiness-report"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AAROGYA -- CAPABILITY TRUTH MATRIX" in captured.out
    assert "AAROGYA -- TECHNICAL READINESS & COMPETITION ASSESSMENT REPORT" in captured.out


def test_demo_environment_isolation_and_cleanup(tmp_path):
    """Verify isolated database file is removed after run_demo."""
    db_file = str(tmp_path / "test_iso_cleanup.db")
    orchestrator = CompetitionDemoOrchestrator(db_path=db_file)
    res = orchestrator.run_demo(DemoScenarioKey.FAMILY_MEDICINE)
    assert res is not None
    # Database path was closed and deleted by the runner
    assert not os.path.exists(db_file)
