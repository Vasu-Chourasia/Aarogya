# Aarogya Architecture Overview
### Comprehensive System Context, Operational Workflows, Safety Gates, and Integration Boundaries

---

## 1. System Context & Operational Architecture

Aarogya is an AI-powered Family Healthcare Coordination Agent designed to orchestrate complex chronic care workflows for families. Built using Python 3.11, LangGraph, Pydantic, and AgenticOrg, Aarogya bridges family caregivers, elderly patients, verified clinical prescriptions, and external healthcare providers (pharmacies, logistics, and task backends).

```mermaid
C4Context
    title System Context Diagram -- Aarogya Family Healthcare Coordinator

    Person(caregiver, "Family Caregiver", "Family member managing chronic care remotely.")
    Person(patient, "Patient (Elderly Parent)", "Individual receiving coordinated family healthcare.")
    
    System(aarogya, "Aarogya Healthcare Coordinator", "LangGraph orchestrator, Family Health Brain, and Execution Gateway.")
    
    System_Ext(agenticorg, "AgenticOrg Fleet Platform", "Tenant discovery, connector registration, and fleet policy.")
    System_Ext(pharmacy, "Direct Pharmacy API (Apollo)", "Direct pharmacy catalog, inventory, pricing, and coverage.")
    System_Ext(logistics, "Logistics Courier (Delhivery)", "Physical package tracking and proof-of-delivery.")
    System_Ext(emergency, "Emergency Services (108 / 112)", "National emergency tele-dispatch network.")
    SystemDb(sqlite, "Durable SQLite Storage", "Capabilities, executions, idempotency, approvals, and audit logs.")

    Rel(caregiver, aarogya, "Submits healthcare requests via Chat / CLI", "HTTPS / JSON")
    Rel(aarogya, patient, "Delivers reminders & updates", "SMS / WhatsApp")
    Rel(aarogya, agenticorg, "Discovers tenant connectors (Read-Only)", "SDK / REST")
    Rel(aarogya, pharmacy, "Queries inventory & prices (Simulated)", "HTTPS / REST")
    Rel(aarogya, emergency, "Directs user during acute crises", "Clinical Triage")
    Rel(aarogya, sqlite, "Persists state & audit trails", "SQLite3 / WAL")
```

---

## 2. Core Components & Responsibilities

The codebase in `aarogya/` is organized into modular services with strict separation of concerns:

```mermaid
graph TD
    subgraph Ingestion & Understanding
        RP[RequestUnderstandingService\nModule 1]
    end

    subgraph Clinical Context & Authority
        FHB[(FamilyHealthBrain\nVerified Records)]
        AUTH[HealthcareAuthorizationEngine\nFamily Circle Scope]
    end

    subgraph Capability Management
        AD[AgenticOrgDiscoveryService\nModule 7]
        CS[CapabilitySynchronizer\nModule 8]
        CR[ConnectorRegistry\nModule 2]
    end

    subgraph Safety & Execution Governance
        EG[ExecutionGateway\n10 Policy Gates - Module 9]
        AM[ApprovalManager\nHITL Parameter Binding - Module 5]
        OV[OutcomeVerificationService\nEvidence Verification - Module 6]
        AL[AuditLogger\nTamper-Evident Redaction]
    end

    subgraph Operational Adapters & Workflows
        PA[Direct Pharmacy Adapter\nApollo Direct - Module 11]
        MW[MedicineAvailabilityWorkflow\nModule 3]
        CW[CaregiverTaskWorkflow\nModule 4]
    end

    subgraph Durable Storage
        DB[(Durable SQLite Storage\nModule 10)]
    end

    RP --> AUTH
    AUTH --> FHB
    AUTH --> EG
    AD --> CS --> CR --> EG
    EG --> AM
    EG --> PA
    EG --> MW
    EG --> CW
    PA --> OV
    EG --> AL --> DB
    EG --> DB
```

| Component | Primary Responsibility | Key Files |
|---|---|---|
| **RequestUnderstandingService** | Entity extraction, intent classification, red-flag emergency symptom detection, and confidence scoring. | `aarogya/understanding/request_parser.py` |
| **FamilyHealthBrain** | Verified patient records, active doctor prescriptions, household medicine stock, and authorized family circles. | `aarogya/brain/family_health_brain.py` |
| **HealthcareAuthorizationEngine** | Fine-grained permission checks ensuring caregivers only access authorized patient records. | `aarogya/orchestrator/agent.py` |
| **CapabilitySynchronizer** | Discovery, normalization, domain classification, and registry reconciliation for external connectors. | `aarogya/connectors/capability_synchronizer.py` |
| **ExecutionGateway** | Controlled 10-gate policy gateway governing all tool invocations and enforcing simulation mode. | `aarogya/orchestrator/execution_gateway.py` |
| **ApprovalManager** | Cryptographic parameter hash binding and lifecycle management for human-in-the-loop approvals. | `aarogya/workflows/approval_manager.py` |
| **PharmacyProviderAdapter** | Vendor-agnostic pharmacy integration interface with Apollo Direct mock implementation. | `aarogya/connectors/pharmacy_adapter.py` |
| **OutcomeVerificationService** | Evidence-based outcome evaluation distinguishing API dispatch from real-world physical delivery. | `aarogya/orchestrator/agent.py` |
| **PersistenceBundle** | SQLite-backed durable repositories for capabilities, executions, idempotency, and audit trails. | `aarogya/persistence/` |

---

## 3. Data Flow & Orchestration Pipeline

```mermaid
sequenceDiagram
    autonumber
    actor Caregiver as Caregiver (Amit)
    participant Agent as AarogyaAgent (LangGraph)
    participant Brain as FamilyHealthBrain
    participant Gateway as ExecutionGateway (10 Gates)
    participant Adapter as PharmacyAdapter (Apollo)
    participant Approvals as ApprovalManager (HITL)
    participant DB as SQLite Storage

    Caregiver->>Agent: "Check if father's Medicine X needs refill and coordinate it"
    Agent->>Agent: RequestUnderstanding (Entity extraction & Confidence check)
    Agent->>Brain: Resolve patient 'father' -> 'pat_rajesh_01'
    Brain-->>Agent: PatientRecord (Rajesh Kumar, Rx #rx_rajesh_01, Stock: 4 days)
    Agent->>Agent: PolicyAuthorizationEngine (Verify Amit in caregiver circle)
    
    Agent->>Gateway: ExecutionRequest (check_inventory, Medicine X, qty=30)
    Gateway->>Gateway: Enforce 10 Safety Gates (Allowlist, Schema, Confidence >= 88%)
    Gateway->>Adapter: check_inventory(medicine_name="Medicine X", quantity=30)
    Adapter-->>Gateway: PharmacyInventoryDetails (AVAILABLE, Stock=100, Price=Rs. 145.50)
    Gateway->>DB: Persist ExecutionRecord & AuditLogEntry
    Gateway-->>Agent: ExecutionResult (AVAILABLE)

    Agent->>Approvals: request_approval(action=CREATE_CAREGIVER_TASK, params={...})
    Approvals->>DB: Persist ApprovalRecord (Status: PENDING, ParamHash: 953637e...)
    Approvals-->>Agent: ApprovalRecord (appr_...)
    
    Agent-->>Caregiver: Response (Stock available, refill task proposed, AWAITING_APPROVAL)
```

---

## 4. The 10 Safety Gates in the Execution Gateway

Before any external connector or MCP tool can execute, it must pass through all 10 gates in [`ExecutionGateway.execute()`](file:///d:/Ken%20Case%20Competition/Healthcare%20Backend/aarogya/orchestrator/execution_gateway.py):

```mermaid
flowchart TD
    Req([Incoming ExecutionRequest]) --> G1{Gate 1: Capability Registered?}
    G1 -- No --> Block[Blocked / Rejected]
    G1 -- Yes --> G2{Gate 2: Operational Readiness?\nRegistered, Auth, Conn, Healthy, Not Stale}
    G2 -- Unready --> Block
    G2 -- Ready --> G3{Gate 3: Domain & Operation Allowlist?\nApproved operation for healthcare domain}
    G3 -- Disallowed --> Block
    G3 -- Allowed --> G4{Gate 4: Schema Validation?\nextra='forbid' & Injection Guard}
    G4 -- Invalid / Injection --> Block
    G4 -- Valid --> G5{Gate 5: Healthcare Authorization?\nRequester in Patient Circle}
    G5 -- Unauthorized --> Block
    G5 -- Authorized --> G6{Gate 6: Confidence Floor?\nScore >= 88%}
    G6 -- Below 88% --> Block
    G6 -- Meets Floor --> G7{Gate 7: Consequential Action Approval?\nHITL Approval Record Valid & Bound}
    G7 -- Missing / Mismatch --> Block
    G7 -- Approved / Read-Only --> G8{Gate 8: Execution Mode Policy?\nLive Operations Strictly Disabled}
    G8 -- Live Attempt --> Block
    G8 -- Simulation / Shadow --> G9{Gate 9: Idempotency Protection?\nCached duplicate check}
    G9 -- Duplicate Found --> ReturnCache([Return Cached Result])
    G9 -- New Key --> G10[Gate 10: Approved Synthetic Handler Dispatch]
    G10 --> Result([Outcome Verification & Persistence])
```

---

## 5. Human-in-the-Loop (HITL) Approval Cryptography

Aarogya protects families against unauthorized or altered consequential operations through cryptographic parameter binding:

$$\text{Parameter Digest} = \text{SHA256}(\text{JSON-sorted-normalized-parameters})$$

1. **Request Binding:** The approval record binds to `(request_id, user_identity, action_type, parameter_hash)`.
2. **Tamper Rejection:** When an approval is granted, provided parameters are re-hashed. If an attacker modifies the quantity (e.g., from 30 to 999 tablets), the approval is **automatically revoked** with reason `"Parameters changed materially from original request"`.
3. **Time Expiration:** Approval records include an explicit `expiration` timestamp (default: 60 minutes). Expired approvals cannot be approved or dispatched.

---

## 6. Clinical Emergency Fast-Path & Triage

When acute life-threatening symptoms are reported, standard workflow execution is bypassed immediately:

```mermaid
flowchart LR
    UserInput([User Query]) --> SymptomCheck{Red-Flag Symptoms?\nChest pain, dyspnea, stroke signs}
    
    SymptomCheck -- Yes --> EmergencyPath[Emergency Fast-Path\nClassified as EMERGENCY\nConfidence = 1.0]
    EmergencyPath --> Guidance[Direct user to call 108 / 112\nor visit nearest emergency department]
    Guidance --> AuditEmergency[Persist Emergency Safety Audit Event]
    AuditEmergency --> DoneEmergency([Zero Order Delay / Zero Medical Diagnosis])
    
    SymptomCheck -- No --> StandardPath[Standard Intent Classification\nConfidence Floor: 88%]
    StandardPath --> Coordination[Proceed to Family Coordination]
```

### Safety Constraints in Emergency Mode:
* **No Diagnostic Speculation:** Aarogya never diagnoses ("You are having a heart attack").
* **No Administrative Delay:** It does not initiate routine pharmacy checks or task creation.
* **Truthful Disclaimer:** It explicitly clarifies that Aarogya is an AI coordinator and did **NOT** dial emergency services on the user's behalf.

---

## 7. Failure Handling & Failure-to-Confirm States

When external dependencies fail, Aarogya enforces defensive failure containment:

```mermaid
stateDiagram-v2
    [*] --> InFlight: Gateway Dispatch
    InFlight --> SUCCESS: Provider Responded
    InFlight --> TIMED_OUT: Upstream Timeout (No Data Fabrication)
    InFlight --> UNKNOWN_OUTCOME: Network Loss After Dispatch
    
    UNKNOWN_OUTCOME --> REQUIRES_VERIFICATION: Duplicate Retry Intercepted
    REQUIRES_VERIFICATION --> VERIFIED: Manual Reconciliation Completed
    REQUIRES_VERIFICATION --> CANCELLED: Safe Rollback / Cancellation
```

1. **Timeout Handling:** Network timeouts trigger `TIMEOUT` error category. Availability status remains `UNKNOWN/TIMEOUT`. **Zero stock or pricing is hallucinated.**
2. **Uncertain Outcomes (`UNKNOWN_OUTCOME`):** If an operation is dispatched but confirmation drops, the record is flagged as uncertain. Subsequent retries with the same idempotency key are **blocked by policy** and transition to `REQUIRES_VERIFICATION`. Automatic double-dispatch is strictly prevented.

---

## 8. Durable Persistence & SQLite Schema

Durable relational persistence is implemented in `aarogya/persistence/` using SQLite with Write-Ahead Logging (`WAL`):

* `capabilities`: Normalized connector metadata, source platform, and readiness flags.
* `sync_history`: Capability synchronization run history and audit counts.
* `execution_records`: Detailed gateway execution results, verification status, and latencies.
* `idempotency_records`: Cryptographic idempotency key locks and execution mappings.
* `approval_records`: HITL approval requests, parameter hashes, and grant history.
* `audit_events`: Tamper-evident structured audit trail with automated secret redaction.

---

## 9. Production Readiness & Integration Boundaries

| Integration Point | Current Architectural State | Operational Safety Boundary | Requirements for Production |
|---|---|---|---|
| **Direct Pharmacy API** | Apollo Direct Mock Provider | Sandbox / Simulation only | Signed B2B API agreement, HIPAA/DISHA partner review. |
| **AgenticOrg Platform** | Read-Only Tenant Discovery | Zero execution of unknown MCP tools | Provisioned tenant credentials (`AGENTICORG_API_KEY`). |
| **Caregiver Tasks** | Local Development Task Backend | Gated behind HITL approval boundary | Integration with enterprise family task engine. |
| **Payments (Pine Labs)**| Input Contract Schemas Defined | Gated behind Gate 7 & Gate 8 policy | Payment aggregator merchant credentials and tokenization. |
| **Logistics (Delhivery)**| Input Contract Schemas Defined | Gated behind POD outcome verification | Webhook ingestion endpoints for courier status callbacks. |
| **Emergency (108/112)** | Text Triage Direction | No automated call placement | Integration with accredited emergency tele-dispatch networks. |
