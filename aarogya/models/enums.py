"""Domain Enums for Aarogya Healthcare Coordinator."""

from enum import Enum


class ExecutionMode(str, Enum):
    """System runtime modes."""
    SIMULATION = "SIMULATION"
    CONNECTED_READ_ONLY = "CONNECTED_READ_ONLY"
    AUTHORIZED_EXECUTION = "AUTHORIZED_EXECUTION"


class RequestType(str, Enum):
    """Categorized incoming healthcare request types."""
    MEDICINE_AVAILABILITY_CHECK = "medicine_availability_check"
    CAREGIVER_TASK_CREATION = "caregiver_task_creation"
    MEDICINE_ORDER = "medicine_order"
    PRESCRIPTION_VERIFICATION = "prescription_verification"
    APPOINTMENT_COORDINATION = "appointment_coordination"
    REFILL_COORDINATION = "refill_coordination"
    EMERGENCY = "emergency"
    GENERAL_INQUIRY = "general_inquiry"


class ExecutionStatus(str, Enum):
    """Status of the request execution workflow."""
    RECEIVED = "received"
    BLOCKED_MISSING_INFORMATION = "blocked_missing_information"
    BLOCKED_CONNECTOR_MISSING = "blocked_connector_missing"
    BLOCKED_UNAUTHORIZED = "blocked_unauthorized"
    ROUTED_TO_EMERGENCY = "routed_to_emergency"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_FOR_EXECUTION = "ready_for_execution"
    EXECUTED = "executed"
    FAILED = "failed"


class MedicineAvailabilityOutcome(str, Enum):
    """Standardized medicine availability outcomes."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    ALTERNATIVE_SOURCE_REQUIRED = "ALTERNATIVE_SOURCE_REQUIRED"
    INTEGRATION_UNAVAILABLE = "INTEGRATION_UNAVAILABLE"
    MISSING_PRESCRIPTION = "MISSING_PRESCRIPTION"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNKNOWN = "UNKNOWN"


class TaskStatus(str, Enum):
    """Controlled lifecycle states for caregiver tasks."""
    DRAFT = "DRAFT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED_PENDING_VERIFICATION = "COMPLETED_PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TaskPriority(str, Enum):
    """Task urgency levels."""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ApprovalStatus(str, Enum):
    """HITL Approval statuses."""
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ActionType(str, Enum):
    """Consequential action categories requiring explicit approval."""
    CREATE_CAREGIVER_TASK = "create_caregiver_task"
    SEND_HEALTHCARE_COMMUNICATION = "send_healthcare_communication"
    PLACE_MEDICINE_ORDER = "place_medicine_order"
    BOOK_APPOINTMENT = "book_appointment"
    INITIATE_PAYMENT = "initiate_payment"
    MODIFY_HEALTHCARE_RECORD = "modify_healthcare_record"


class VerificationStatus(str, Enum):
    """Outcome verification state."""
    NOT_APPLICABLE = "not_applicable"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    VERIFICATION_FAILED = "verification_failed"


class AgenticOrgAuthState(str, Enum):
    """Explicit AgenticOrg integration and authentication states."""
    NOT_CONFIGURED = "NOT_CONFIGURED"
    INITIALIZING = "INITIALIZING"
    AUTHENTICATED = "AUTHENTICATED"
    AUTH_FAILED = "AUTH_FAILED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED = "UNSUPPORTED"
    DISCOVERY_FAILED = "DISCOVERY_FAILED"


class DiscoveryStatus(str, Enum):
    """Tenant discovery execution status."""
    NOT_STARTED = "not_started"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class HealthcareDomain(str, Enum):
    """Potential healthcare domains for capability classification."""
    MEDICINE_AVAILABILITY = "MEDICINE_AVAILABILITY"
    MEDICINE_ORDERING = "MEDICINE_ORDERING"
    APPOINTMENT_DISCOVERY = "APPOINTMENT_DISCOVERY"
    APPOINTMENT_BOOKING = "APPOINTMENT_BOOKING"
    CAREGIVER_TASKS = "CAREGIVER_TASKS"
    PAYMENTS = "PAYMENTS"
    VOICE_COMMUNICATION = "VOICE_COMMUNICATION"
    DOCUMENT_INGESTION = "DOCUMENT_INGESTION"
    LOGISTICS = "LOGISTICS"
    UNKNOWN = "UNKNOWN"


class CapabilityPolicyDecision(str, Enum):
    """Explicit policy decisions for connector and MCP operational capabilities."""
    ELIGIBLE_FOR_POLICY_REVIEW = "ELIGIBLE_FOR_POLICY_REVIEW"
    BLOCKED_NOT_REGISTERED = "BLOCKED_NOT_REGISTERED"
    BLOCKED_UNAUTHORIZED = "BLOCKED_UNAUTHORIZED"
    BLOCKED_UNHEALTHY = "BLOCKED_UNHEALTHY"
    BLOCKED_UNKNOWN_CAPABILITY = "BLOCKED_UNKNOWN_CAPABILITY"
    BLOCKED_UNSUPPORTED_OPERATION = "BLOCKED_UNSUPPORTED_OPERATION"
    BLOCKED_STALE_METADATA = "BLOCKED_STALE_METADATA"


class AuditEventType(str, Enum):
    """Structured audit trail events."""
    REQUEST_RECEIVED = "request_received"
    PATIENT_RESOLVED = "patient_resolved"
    PRESCRIPTION_RESOLVED = "prescription_resolved"
    CONNECTOR_DISCOVERED = "connector_discovered"
    CAPABILITY_CHECK_COMPLETED = "capability_check_completed"
    AUTHORIZATION_EVALUATED = "authorization_evaluated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    OPERATION_EXECUTED = "operation_executed"
    PROVIDER_RESPONSE_RECEIVED = "provider_response_received"
    VERIFICATION_COMPLETED = "verification_completed"
    OPERATION_BLOCKED = "operation_blocked"
    OPERATION_FAILED = "operation_failed"
    EMERGENCY_ROUTED = "emergency_routed"
    NOTIFICATION_SENT = "notification_sent"

    # Module 7: AgenticOrg Authentication & Tenant Discovery Events
    DISCOVERY_STARTED = "discovery_started"
    CREDENTIALS_MISSING = "credentials_missing"
    SDK_INITIALIZATION_COMPLETED = "sdk_initialization_completed"
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    CONNECTOR_DISCOVERY_SUCCEEDED = "connector_discovery_succeeded"
    MCP_DISCOVERY_SUCCEEDED = "mcp_discovery_succeeded"
    PARTIAL_DISCOVERY = "partial_discovery"
    DISCOVERY_FAILED = "discovery_failed"
    DISCOVERY_COMPLETED = "discovery_completed"

    # Module 8: Capability Synchronization & Reconciliation Events
    CAPABILITY_SYNC_STARTED = "capability_sync_started"
    CAPABILITY_SYNC_COMPLETED = "capability_sync_completed"
    CAPABILITY_SYNC_FAILED = "capability_sync_failed"
    CAPABILITY_RECONCILED = "capability_reconciled"
    CAPABILITY_MARKED_STALE = "capability_marked_stale"

    # Module 9: Controlled Tool Invocation & Execution Gateway Events
    GATEWAY_EXECUTION_REQUESTED = "gateway_execution_requested"
    GATEWAY_EXECUTION_BLOCKED = "gateway_execution_blocked"
    GATEWAY_EXECUTION_REJECTED = "gateway_execution_rejected"
    GATEWAY_EXECUTION_SIMULATED = "gateway_execution_simulated"
    GATEWAY_EXECUTION_SUCCEEDED = "gateway_execution_succeeded"
    GATEWAY_EXECUTION_FAILED = "gateway_execution_failed"
    GATEWAY_EXECUTION_TIMEOUT = "gateway_execution_timeout"
    GATEWAY_IDEMPOTENCY_MATCHED = "gateway_idempotency_matched"
    GATEWAY_VERIFICATION_REQUIRED = "gateway_verification_required"

    # Phase 14: Appointment & Voice Coordination Events
    APPOINTMENT_REQUESTED = "appointment_requested"
    APPOINTMENT_SLOTS_RECEIVED = "appointment_slots_received"
    APPOINTMENT_APPROVED = "appointment_approved"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_FAILED = "appointment_failed"
    VOICE_CALL_INITIATED = "voice_call_initiated"
    VOICE_OUTCOME_RECEIVED = "voice_outcome_received"


class GatewayExecutionStatus(str, Enum):
    """Explicit statuses for controlled gateway tool invocation lifecycle."""
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    READY = "READY"
    SIMULATED = "SIMULATED"
    SUBMITTED = "SUBMITTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"


class AppointmentStatus(str, Enum):
    """Lifecycle statuses for healthcare appointment coordination."""
    REQUESTED = "REQUESTED"
    AVAILABILITY_PENDING = "AVAILABILITY_PENDING"
    SLOTS_RECEIVED = "SLOTS_RECEIVED"
    AWAITING_PATIENT_APPROVAL = "AWAITING_PATIENT_APPROVAL"
    APPROVED = "APPROVED"
    BOOKING_IN_PROGRESS = "BOOKING_IN_PROGRESS"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class VoiceCallStatus(str, Enum):
    """Lifecycle statuses for external voice coordination calls."""
    SCHEDULED = "SCHEDULED"
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class VoiceCallDisposition(str, Enum):
    """Structured outcomes from voice-based clinic coordination."""
    SLOTS_OFFERED = "SLOTS_OFFERED"
    NO_SLOTS_AVAILABLE = "NO_SLOTS_AVAILABLE"
    CLINIC_BUSY = "CLINIC_BUSY"
    CALL_DISCONNECTED = "CALL_DISCONNECTED"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    BOOKING_REJECTED = "BOOKING_REJECTED"
    CALLBACK_REQUESTED = "CALLBACK_REQUESTED"
    UNKNOWN = "UNKNOWN"

