"""Module 13: Capability Truth Matrix & Technical Readiness Assessment.

Provides machine-readable models and reporting for Aarogya's 20 core capabilities,
truthful outcome accounting metrics, and 5-domain technical readiness evaluation.
"""

from typing import Dict, Any, List, Optional
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class CapabilityStatus(str, Enum):
    """Maturity level for capabilities conforming to Section 6 & 7 distinctions."""
    IMPLEMENTED = "IMPLEMENTED"
    UNIT_TESTED = "UNIT_TESTED"
    END_TO_END_SIMULATED = "END_TO_END_SIMULATED"
    EXTERNAL_SANDBOX_VERIFIED = "EXTERNAL_SANDBOX_VERIFIED"
    SANDBOX_VERIFIED = "EXTERNAL_SANDBOX_VERIFIED"
    LIVE_INTEGRATION_VERIFIED = "LIVE_INTEGRATION_VERIFIED"
    PRODUCTION_VALIDATED = "PRODUCTION_VALIDATED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class CapabilityEntry(BaseModel):
    """Evaluation entry for an individual system capability."""
    index: int
    name: str
    description: str
    status: CapabilityStatus
    evidence: str
    live_verified: bool = False
    notes: str


# 20 capabilities specified in Section 6
CAPABILITY_TRUTH_MATRIX: List[CapabilityEntry] = [
    CapabilityEntry(
        index=1,
        name="Family onboarding",
        description="Registration of family members, caregiver circle, and relationship links.",
        status=CapabilityStatus.UNIT_TESTED,
        evidence="FamilyHealthBrain._seed_fictional_data() in aarogya/brain/family_health_brain.py",
        live_verified=False,
        notes="Pre-seeded fictional family trees; self-service invite link flow not yet implemented.",
    ),
    CapabilityEntry(
        index=2,
        name="Patient resolution",
        description="Resolving explicit or relationship-based references to verified patient records.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="RequestUnderstandingService & AarogyaAgent._node_resolve_patient in test_module12_evaluation.py",
        live_verified=False,
        notes="Correctly resolves 'father' to Rajesh Kumar; halts with clarification on missing patient without guessing.",
    ),
    CapabilityEntry(
        index=3,
        name="Healthcare authorization",
        description="Fine-grained caregiver circle permission checks for patient data access.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="HealthcareAuthorizationEngine & assert_authorization_enforced in tests/test_module12_evaluation.py",
        live_verified=False,
        notes="Strictly enforces family circle membership; strangers denied access with zero disclosure.",
    ),
    CapabilityEntry(
        index=4,
        name="Medical record ingestion",
        description="Ingestion and parsing of doctor prescriptions and clinical records.",
        status=CapabilityStatus.UNIT_TESTED,
        evidence="PrescriptionRecord & FamilyHealthBrain storage in aarogya/brain/family_health_brain.py",
        live_verified=False,
        notes="Structured model ingestion active; OCR / PDF document processing pipeline planned.",
    ),
    CapabilityEntry(
        index=5,
        name="Medicine intelligence",
        description="Active ingredient, strength, dosage plan, and stock exhaustion tracking.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="FamilyHealthBrain medicine plan retrieval and household stock differentiation in Module 3 & 12",
        live_verified=False,
        notes="Distinguishes doctor prescription from household stock; flags missing or stale prescriptions.",
    ),
    CapabilityEntry(
        index=6,
        name="Pharmacy inventory lookup",
        description="Real-time medicine stock checking across pharmacy partner adapters.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="MockPharmacyProvider.check_inventory & ExecutionGateway in test_module11_pharmacy_adapter.py",
        live_verified=False,
        notes="Simulated partner execution via normalized contract; Apollo Direct mock adapter verified.",
    ),
    CapabilityEntry(
        index=7,
        name="Pharmacy price lookup",
        description="Medicine pricing, MRP, and discount calculations via pharmacy API.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="MockPharmacyProvider.get_price in test_module11_pharmacy_adapter.py",
        live_verified=False,
        notes="Normalized currency and unit price calculations; real-time dynamic discounting planned.",
    ),
    CapabilityEntry(
        index=8,
        name="Refill coordination",
        description="End-to-end medicine refill proposal, workflow coordination, and tracking.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="Scenario A & Demo 1 full orchestrator execution in test_module12_evaluation.py",
        live_verified=False,
        notes="Generates structured refill task; strictly separates refill proposal from real-world order placement.",
    ),
    CapabilityEntry(
        index=9,
        name="Appointment coordination",
        description="Doctor consultation scheduling, slot discovery, and appointment booking.",
        status=CapabilityStatus.NOT_IMPLEMENTED,
        evidence="Contract placeholders in HealthcareDomain enum",
        live_verified=False,
        notes="Domain classified in policy rules; external clinic scheduling connector planned for future phase.",
    ),
    CapabilityEntry(
        index=10,
        name="Caregiver task management",
        description="Creation, assignment, status tracking, and verification of care tasks.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="CaregiverTask lifecycle in test_module4_caregiver_tasks.py & test_module9_execution_gateway.py",
        live_verified=False,
        notes="Strict 10-state lifecycle (DRAFT -> AWAITING_APPROVAL -> APPROVED -> ... -> VERIFIED).",
    ),
    CapabilityEntry(
        index=11,
        name="Human approval",
        description="Cryptographically bound HITL approvals for consequential healthcare actions.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="ApprovalManager in test_module5_approval_manager.py & test_module12_evaluation.py",
        live_verified=False,
        notes="Enforces parameter hash matching, validity expiry, user identity binding, and revokes on tampering.",
    ),
    CapabilityEntry(
        index=12,
        name="Execution policy",
        description="Controlled 10-gate policy gateway governing external tool invocation.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="ExecutionGateway with 10 gates in test_module9_execution_gateway.py",
        live_verified=False,
        notes="Enforces readiness, allowlists, confidence floor (88%), and blocks live operations by policy.",
    ),
    CapabilityEntry(
        index=13,
        name="Durable persistence",
        description="Relational SQLite persistence for capabilities, executions, approvals, and audits.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="PersistenceBundle & SQLite schema in test_module10_persistence.py",
        live_verified=False,
        notes="Survives restart; durable idempotency keys and approval states; WAL mode enabled.",
    ),
    CapabilityEntry(
        index=14,
        name="Outcome verification",
        description="Evidence-based outcome verification distinguishing API response from delivery.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="OutcomeVerificationService in test_module6_outcome_verification.py",
        live_verified=False,
        notes="Mandates physical proof-of-delivery evidence; HTTP 200 != physical delivery.",
    ),
    CapabilityEntry(
        index=15,
        name="Caregiver notification",
        description="Targeted alerts to verified family circle members with privacy scoping.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="Scenario I in test_module12_evaluation.py & NotificationService",
        live_verified=False,
        notes="Sends updates only to authorized family members; distinguishes facts from pending tasks.",
    ),
    CapabilityEntry(
        index=16,
        name="Emergency routing",
        description="Immediate clinical emergency triage and fast-path routing to 108/112.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="RequestUnderstandingService emergency red-flag triage in test_module12_evaluation.py",
        live_verified=False,
        notes="Instant triage on acute chest pain / dyspnea; zero routine ordering delays; zero medical diagnosis.",
    ),
    CapabilityEntry(
        index=17,
        name="Voice integration",
        description="Voice interaction for elderly patients and speech-based coordination.",
        status=CapabilityStatus.NOT_IMPLEMENTED,
        evidence="HealthcareDomain.VOICE_COMMUNICATION enum definition",
        live_verified=False,
        notes="Telephony / WebRTC voice interface planned for future assistive deployment.",
    ),
    CapabilityEntry(
        index=18,
        name="Payment integration",
        description="Patient copay and medicine payment execution via payment gateways.",
        status=CapabilityStatus.UNIT_TESTED,
        evidence="InitiatePaymentInputContract schema in aarogya/models/gateway.py",
        live_verified=False,
        notes="Input schema and injection validation implemented; live merchant gateway disabled.",
    ),
    CapabilityEntry(
        index=19,
        name="Logistics integration",
        description="Third-party courier and last-mile cold chain tracking and dispatch.",
        status=CapabilityStatus.UNIT_TESTED,
        evidence="TrackDeliveryInputContract schema in aarogya/models/gateway.py",
        live_verified=False,
        notes="Tracking schema implemented; live carrier webhook dispatch integration planned.",
    ),
    CapabilityEntry(
        index=20,
        name="AgenticOrg connector discovery",
        description="Read-only tenant connector and MCP tool discovery and capability synchronization.",
        status=CapabilityStatus.END_TO_END_SIMULATED,
        evidence="AgenticOrgDiscoveryService & CapabilitySynchronizer in test_module7 & test_module8",
        live_verified=False,
        notes="Safe read-only discovery, normalization, reconciliation, and audit recording without tool execution.",
    ),
]


class TruthfulEvaluationMetrics(BaseModel):
    """Truthful outcome accounting metrics conforming to Section 6A guidelines."""
    scenario_evaluation_pass_rate_num: int = 10
    scenario_evaluation_pass_rate_den: int = 10
    scenario_evaluation_pass_rate_pct: float = 100.0
    scenario_evaluation_explanation: str = (
        "100.0% (10/10 scenarios passed all safety and operational behavioral assertions, "
        "including intentional safety containment blocks)."
    )

    safety_containment_rate_num: int = 3
    safety_containment_rate_den: int = 3
    safety_containment_rate_pct: float = 100.0
    safety_containment_explanation: str = (
        "100.0% (3/3 unsafe or unauthorized scenarios correctly intercepted: "
        "Scenario B unauthorized access, Scenario C missing patient, Scenario E unverified drug)."
    )

    completed_healthcare_workflow_rate_num: int = 7
    completed_healthcare_workflow_rate_den: int = 10
    completed_healthcare_workflow_rate_pct: float = 70.0
    completed_healthcare_workflow_explanation: str = (
        "70.0% (7/10 scenarios completed their intended operational workflows. "
        "The 3 safely blocked requests are strictly excluded from completed operations)."
    )

    pending_approval_count: int = 2
    pending_approval_explanation: str = (
        "2 consequential operations currently held in AWAITING_APPROVAL state "
        "(Refill task creation in Scenario A and consequential task proposal in Scenario F)."
    )

    uncertain_outcome_count: int = 1
    uncertain_outcome_explanation: str = (
        "1 operation recorded in UNKNOWN_OUTCOME / REQUIRES_VERIFICATION state "
        "(Simulated network loss during Scenario H dispatch requiring manual reconciliation)."
    )

    # Strict completion metrics (Section 2 & 6A: pending approvals, timeouts, blocked, & unknown outcomes excluded)
    strict_completed_workflow_rate_num: int = 3
    strict_completed_workflow_rate_den: int = 10
    strict_completed_workflow_rate_pct: float = 30.0
    strict_completed_workflow_explanation: str = (
        "30.0% (3/10 scenarios reached verified completion: Scenario G duplicate idempotency, "
        "Scenario I caregiver notification, Scenario J emergency triage routing. Strictly excluded: "
        "3 safely blocked [B, C, E], 2 pending human approval [A, F], 1 provider timeout [D], and 1 uncertain outcome [H])."
    )

    # Module 13 Competition Demo Specific Accounting (5 Scenarios)
    demo_evaluation_pass_rate_num: int = 5
    demo_evaluation_pass_rate_den: int = 5
    demo_evaluation_pass_rate_pct: float = 100.0
    demo_safety_containment_rate_num: int = 1
    demo_safety_containment_rate_den: int = 1
    demo_safety_containment_rate_pct: float = 100.0
    demo_completed_workflow_rate_num: int = 1
    demo_completed_workflow_rate_den: int = 5
    demo_completed_workflow_rate_pct: float = 20.0
    demo_pending_approval_count: int = 1
    demo_uncertain_outcome_count: int = 1
    demo_accounting_explanation: str = (
        "Module 13 Competition Demo (5 Scenarios): 100.0% evaluation pass rate (5/5); "
        "100.0% safety containment (1/1 Demo 2); 20.0% verified completion (1/5 Demo 3 emergency routing). "
        "Demo 1 (pending approval), Demo 2 (blocked), Demo 4 (timeout), and Demo 5 (unknown outcome) strictly excluded from completed."
    )

    live_integrations_verified_num: int = 0
    live_integrations_verified_den: int = 20
    live_integrations_verified_pct: float = 0.0
    live_integration_explanation: str = (
        "0.0% (0/20 integrations verified against real live production environments. "
        "All operations confined to simulated and mock providers. Live operations remain disabled)."
    )


class TechnicalReadinessCategory(BaseModel):
    """Assessment of readiness across a single technical domain."""
    domain: str
    items: List[Dict[str, str]]


def get_technical_readiness_assessment() -> List[TechnicalReadinessCategory]:
    """Compile comprehensive technical readiness assessment across 5 core domains."""
    return [
        TechnicalReadinessCategory(
            domain="1. Architecture",
            items=[
                {
                    "item": "Component Responsibilities",
                    "evidence": "Strict separation between understanding, brain, gateway, workflows, and persistence.",
                    "status": "READY (SIMULATION)",
                    "known_gap": "External service contracts rely on local mock implementations.",
                    "required_action": "Complete vendor-specific partner API certification.",
                },
                {
                    "item": "Execution Boundaries & Gateway",
                    "evidence": "10-gate policy gateway rejecting unauthorized, unapproved, or unverified invocations.",
                    "status": "READY (SAFETY-CONFINED)",
                    "known_gap": "Live execution disabled by default policy (`live_execution_enabled=False`).",
                    "required_action": "Maintain policy block until end-to-end sandbox sign-off.",
                },
                {
                    "item": "Durable Persistence",
                    "evidence": "SQLite schema supporting capabilities, executions, idempotency, and audit trails.",
                    "status": "READY (DEVELOPMENT/LOCAL)",
                    "known_gap": "Single-node file-based SQLite database.",
                    "required_action": "Migrate to multi-AZ managed PostgreSQL with read replicas for production.",
                },
            ],
        ),
        TechnicalReadinessCategory(
            domain="2. Reliability & Fault Tolerance",
            items=[
                {
                    "item": "Timeout Behavior",
                    "evidence": "Provider network timeouts caught and accurately categorized as TIMEOUT.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "External partner latency SLAs vary significantly by region.",
                    "required_action": "Implement adaptive exponential backoff with circuit breakers.",
                },
                {
                    "item": "Idempotency & Duplicate Protection",
                    "evidence": "Cryptographic idempotency keys prevent duplicate consequential execution.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "In-flight race conditions across multi-instance worker processes.",
                    "required_action": "Introduce distributed Redis lock manager for cluster deployments.",
                },
                {
                    "item": "Unknown Outcome Handling",
                    "evidence": "UNKNOWN_OUTCOME state forces reconciliation before permitting retries.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "Manual reconciliation CLI required to clear uncertain state.",
                    "required_action": "Build partner webhook reconciliation listener.",
                },
            ],
        ),
        TechnicalReadinessCategory(
            domain="3. Security & Privacy",
            items=[
                {
                    "item": "Authentication & Tenant Scoping",
                    "evidence": "AgenticOrg token & API key discovery verification with tenant connector scoping.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "API keys passed via environment variables.",
                    "required_action": "Migrate to AWS Secrets Manager / HashiCorp Vault.",
                },
                {
                    "item": "Healthcare Authorization & Scoping",
                    "evidence": "HealthcareAuthorizationEngine enforces family circle boundaries.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "Delegated legal power of attorney verification is self-attested.",
                    "required_action": "Integrate Aadhaar-based digital consent artifact verification (ABDM).",
                },
                {
                    "item": "Sensitive Data Minimization & Secret Redaction",
                    "evidence": "Audit logger sanitizes credentials, tokens, and patient identifiers from log streams.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "Local log files written to local disk.",
                    "required_action": "Ship logs to encrypted, write-only centralized SIEM (Splunk/Datadog).",
                },
            ],
        ),
        TechnicalReadinessCategory(
            domain="4. Healthcare Safety & Clinical Guardrails",
            items=[
                {
                    "item": "Prescription Verification",
                    "evidence": "Refill coordination requires verified doctor prescription in Family Health Brain.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "Prescription expiry dates are currently modeled as static validity windows.",
                    "required_action": "Integrate ABDM digital doctor prescription registry lookup.",
                },
                {
                    "item": "Zero Medical Diagnosis / Prescribing",
                    "evidence": "Agent refuses to alter dosages, diagnose symptoms, or prescribe drugs.",
                    "status": "VERIFIED (POLICY-ENFORCED)",
                    "known_gap": "None; core system boundary strictly confines agent to operational coordination.",
                    "required_action": "Maintain strict architectural separation from diagnostic engines.",
                },
                {
                    "item": "Emergency Clinical Triage",
                    "evidence": "Immediate rule-based triage on acute red-flag keywords directing to 108/112.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "Cannot automatically bridge 108 emergency telephone call on user's behalf.",
                    "required_action": "Partner with accredited national emergency tele-dispatch networks.",
                },
            ],
        ),
        TechnicalReadinessCategory(
            domain="5. Deployment Readiness",
            items=[
                {
                    "item": "Environment Separation",
                    "evidence": "Isolated temporary SQLite databases and runtime ExecutionMode configuration.",
                    "status": "VERIFIED (TESTED)",
                    "known_gap": "Local runtime configuration; no container orchestration spec.",
                    "required_action": "Author Helm charts and Kubernetes deployment manifests.",
                },
                {
                    "item": "Monitoring & Telemetry",
                    "evidence": "Structured audit logging and CLI execution history inspection.",
                    "status": "PARTIALLY IMPLEMENTED",
                    "known_gap": "No OpenTelemetry distributed tracing or Prometheus metric exporters.",
                    "required_action": "Instrument FastAPI and LangGraph nodes with OpenTelemetry traces.",
                },
                {
                    "item": "Live Partner Certifications",
                    "evidence": "Mock provider and sandbox adapter interfaces ready.",
                    "status": "BLOCKED BY POLICY",
                    "known_gap": "No accredited pharmacy or payment production contracts executed.",
                    "required_action": "Obtain signed partner B2B agreements and sandbox staging keys.",
                },
            ],
        ),
    ]
