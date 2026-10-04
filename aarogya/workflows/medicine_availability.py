"""Module 3: Medicine Availability Workflow."""

import logging
from typing import Optional, Dict, Any
from ..brain.family_health_brain import FamilyHealthBrain
from ..connectors.registry import ConnectorRegistry
from ..connectors.pharmacy_connector import PharmacyConnectorInterface
from ..policy.authorization_engine import PolicyAuthorizationEngine
from ..models.medicine import MedicineAvailabilityResult
from ..models.enums import MedicineAvailabilityOutcome, ExecutionMode
from ..models.request import ParsedRequest
from .verification import OutcomeVerificationService

logger = logging.getLogger(__name__)


class MedicineAvailabilityWorkflow:
    """Executes the complete Medicine Availability Workflow with strict safety boundaries."""

    def __init__(
        self,
        brain: FamilyHealthBrain,
        connector_registry: ConnectorRegistry,
        policy_engine: PolicyAuthorizationEngine,
        pharmacy_connector: Optional[PharmacyConnectorInterface] = None,
        verification_service: Optional[OutcomeVerificationService] = None,
    ):
        self.brain = brain
        self.connector_registry = connector_registry
        self.policy_engine = policy_engine
        self.pharmacy_connector = pharmacy_connector
        self.verification_service = verification_service or OutcomeVerificationService()

    def process_availability_check(self, parsed: ParsedRequest) -> MedicineAvailabilityResult:
        """Executes full sequence:
        Identify Patient -> Resolve Verified Record -> Retrieve Verified Prescription
        -> Validate Medicine & Quantity -> Check Pharmacy Connector -> Check Authorization
        -> Query Pharmacy -> Validate Provider Response -> Present Result.
        """
        req_id = parsed.request_id
        user_id = parsed.requesting_user
        patient_name = parsed.patient_name
        patient_id = parsed.patient_id
        medicine_name = parsed.medicine_name or "Unknown Medicine"
        quantity = parsed.required_quantity or 0

        # Step 1: Patient Resolution
        if not patient_id and patient_name:
            patient_record = self.brain.get_patient(patient_name)
            if patient_record:
                patient_id = patient_record.patient_id
            else:
                return MedicineAvailabilityResult(
                    outcome=MedicineAvailabilityOutcome.UNKNOWN,
                    patient_id=patient_id or "unresolved",
                    medicine_name=medicine_name,
                    required_quantity=quantity,
                    source="family_health_brain",
                    is_simulated=False,
                    details=f"Could not resolve verified patient record for '{patient_name}'. Operations blocked until patient is identified.",
                )

        if not patient_id:
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.UNKNOWN,
                patient_id="unresolved",
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="family_health_brain",
                is_simulated=False,
                details="Patient identifier missing. Cannot verify prescription without verified patient.",
            )

        # Step 2: Retrieve Verified Prescription
        rx_item = self.brain.find_prescribed_medicine(patient_id, medicine_name)
        rx_record = self.brain.get_verified_prescription(patient_id, medicine_name)
        
        if not rx_item or not rx_record:
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.MISSING_PRESCRIPTION,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="family_health_brain",
                is_simulated=False,
                details=f"No verified prescription found in Family Health Brain for '{medicine_name}' for patient '{patient_id}'. Unprescribed medicine coordination is not permitted.",
            )

        # Step 3: Validate Medicine and Quantity
        if quantity <= 0:
            quantity = rx_item.quantity_prescribed

        # Step 4: Check Authorization
        is_auth, auth_reason = self.policy_engine.authorize_request(
            user_id=user_id,
            patient_id=patient_id,
            action="check_medicine_availability",
        )
        if not is_auth:
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.AUTHORIZATION_REQUIRED,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="policy_authorization_engine",
                is_simulated=False,
                details=f"Authorization check failed: {auth_reason}",
            )

        # Step 5: Check Pharmacy Connector
        # Distinguish simulation mode from production connector availability
        is_sim_mode = self.connector_registry.execution_mode == ExecutionMode.SIMULATION
        cap_check = self.connector_registry.check_capability(
            integration="pharmacy",
            required_capability="check_medicine_availability",
            allow_simulation=is_sim_mode,
        )

        if not cap_check.available:
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.INTEGRATION_UNAVAILABLE,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="connector_registry",
                is_simulated=False,
                details=f"Pharmacy integration unavailable: {cap_check.reason}. Missing requirements: 1. Configured direct pharmacy integration, 2. Healthy connection, 3. Appropriate tenant authorization.",
            )

        # Step 6: Query Pharmacy
        if not self.pharmacy_connector:
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.INTEGRATION_UNAVAILABLE,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="connector_registry",
                is_simulated=False,
                details="No pharmacy connector instance configured or attached.",
            )

        exec_record = self.verification_service.create_execution_record(
            request_id=req_id,
            operation_type="medicine_availability_check",
            status="executing",
        )

        try:
            result = self.pharmacy_connector.check_availability(
                patient_id=patient_id,
                medicine_name=medicine_name,
                quantity=quantity,
                strength=rx_item.strength,
            )
            
            # Step 7: Record outcome in verification service
            if result.outcome in [MedicineAvailabilityOutcome.AVAILABLE, MedicineAvailabilityOutcome.PARTIALLY_AVAILABLE, MedicineAvailabilityOutcome.UNAVAILABLE]:
                self.verification_service.record_execution_success(
                    operation_id=exec_record.operation_id,
                    provider_response=result.raw_provider_response or {"status": result.outcome.value},
                    evidence_description=f"Pharmacy query response: {result.outcome.value} ({result.available_quantity} units)",
                    evidence_source=result.source,
                    is_delivery_or_clinical=False,
                )
            else:
                self.verification_service.record_execution_failure(
                    operation_id=exec_record.operation_id,
                    error_message=result.details,
                    provider_response=result.raw_provider_response,
                )

            return result

        except Exception as e:
            logger.error("Pharmacy connector execution failure: %s", str(e))
            self.verification_service.record_execution_failure(
                operation_id=exec_record.operation_id,
                error_message=str(e),
            )
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.PROVIDER_ERROR,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="pharmacy_connector",
                is_simulated=is_sim_mode,
                details=f"Provider communication failed: {str(e)}. This is a provider error, NOT confirmed medicine unavailability.",
            )
