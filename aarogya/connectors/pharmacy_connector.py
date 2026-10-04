"""Direct Pharmacy API Connector Interface and Implementations."""

import logging
from typing import Optional, Dict, Any
import httpx
from ..models.medicine import MedicineAvailabilityResult
from ..models.enums import MedicineAvailabilityOutcome

logger = logging.getLogger(__name__)


class PharmacyConnectorInterface:
    """Abstract interface for direct pharmacy integration."""
    
    def check_availability(
        self,
        patient_id: str,
        medicine_name: str,
        quantity: int,
        strength: Optional[str] = None,
    ) -> MedicineAvailabilityResult:
        raise NotImplementedError


class LiveDirectPharmacyConnector(PharmacyConnectorInterface):
    """Production direct pharmacy API connector (e.g., Apollo / MedPlus API)."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def check_availability(
        self,
        patient_id: str,
        medicine_name: str,
        quantity: int,
        strength: Optional[str] = None,
    ) -> MedicineAvailabilityResult:
        endpoint = f"{self.base_url}/v1/inventory/check"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "patient_id": patient_id,
            "medicine_name": medicine_name,
            "quantity_requested": quantity,
            "strength": strength,
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(endpoint, json=payload, headers=headers)
                
            if response.status_code == 200:
                data = response.json()
                stock = data.get("available_quantity", 0)
                if stock >= quantity:
                    outcome = MedicineAvailabilityOutcome.AVAILABLE
                elif stock > 0:
                    outcome = MedicineAvailabilityOutcome.PARTIALLY_AVAILABLE
                else:
                    outcome = MedicineAvailabilityOutcome.UNAVAILABLE
                    
                return MedicineAvailabilityResult(
                    outcome=outcome,
                    patient_id=patient_id,
                    medicine_name=medicine_name,
                    required_quantity=quantity,
                    available_quantity=stock,
                    pharmacy_name=data.get("pharmacy_name", "Partner Direct Pharmacy"),
                    pharmacy_id=data.get("pharmacy_id", "pharma_direct_01"),
                    unit_price=data.get("unit_price"),
                    total_estimated_price=data.get("unit_price", 0) * quantity if data.get("unit_price") else None,
                    source=f"live_direct_pharmacy_api ({data.get('pharmacy_name', 'Direct Partner')})",
                    is_simulated=False,
                    details=f"Live inventory confirmed: {stock} units available.",
                    raw_provider_response=data,
                )
            else:
                return MedicineAvailabilityResult(
                    outcome=MedicineAvailabilityOutcome.PROVIDER_ERROR,
                    patient_id=patient_id,
                    medicine_name=medicine_name,
                    required_quantity=quantity,
                    source="live_direct_pharmacy_api",
                    is_simulated=False,
                    details=f"Pharmacy provider returned HTTP error {response.status_code}: {response.text}",
                )

        except httpx.TimeoutException:
            logger.error("Pharmacy API query timed out after %s seconds.", self.timeout_seconds)
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.PROVIDER_ERROR,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="live_direct_pharmacy_api",
                is_simulated=False,
                details=f"Pharmacy API timed out after {self.timeout_seconds}s. This is a provider communication error, NOT confirmed medicine unavailability.",
            )
        except Exception as e:
            logger.error("Pharmacy API query failed: %s", str(e))
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.PROVIDER_ERROR,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="live_direct_pharmacy_api",
                is_simulated=False,
                details=f"Provider error: {str(e)}",
            )


class MockDirectPharmacyConnector(PharmacyConnectorInterface):
    """Explicitly labeled simulated pharmacy connector for development & testing.
    
    All responses clearly declare is_simulated=True and source='simulated_direct_pharmacy_api'.
    """

    def __init__(self, simulate_timeout: bool = False, simulated_inventory: Optional[Dict[str, int]] = None):
        self.simulate_timeout = simulate_timeout
        self.inventory: Dict[str, int] = simulated_inventory or {
            "medicine x": 100,
            "amlodipine": 50,
            "paracetamol": 200,
            "metformin": 80,
            "medicine y": 0,  # Explicitly out of stock in mock
        }

    def check_availability(
        self,
        patient_id: str,
        medicine_name: str,
        quantity: int,
        strength: Optional[str] = None,
    ) -> MedicineAvailabilityResult:
        norm_name = medicine_name.strip().lower()

        if self.simulate_timeout or norm_name == "timeout medicine":
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.PROVIDER_ERROR,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                source="simulated_direct_pharmacy_api",
                is_simulated=True,
                details="Mock pharmacy provider timed out. This is a provider communication error, NOT confirmed medicine unavailability.",
            )

        if norm_name not in self.inventory:
            # Not carried by pharmacy
            return MedicineAvailabilityResult(
                outcome=MedicineAvailabilityOutcome.UNAVAILABLE,
                patient_id=patient_id,
                medicine_name=medicine_name,
                required_quantity=quantity,
                available_quantity=0,
                pharmacy_name="Simulated Apollo Pharmacy, Indiranagar",
                pharmacy_id="sim_pharma_apollo_01",
                source="simulated_direct_pharmacy_api",
                is_simulated=True,
                details=f"Medicine '{medicine_name}' is not in stock at the simulated pharmacy partner.",
            )

        stock = self.inventory[norm_name]
        if stock >= quantity:
            outcome = MedicineAvailabilityOutcome.AVAILABLE
            details = f"Verified in simulated stock: {stock} units available (requested: {quantity})."
        elif stock > 0:
            outcome = MedicineAvailabilityOutcome.PARTIALLY_AVAILABLE
            details = f"Partially available in simulated stock: only {stock} of {quantity} units available."
        else:
            outcome = MedicineAvailabilityOutcome.UNAVAILABLE
            details = f"Medicine '{medicine_name}' is currently out of stock (0 units available) at simulated pharmacy partner."

        unit_price = 12.50
        return MedicineAvailabilityResult(
            outcome=outcome,
            patient_id=patient_id,
            medicine_name=medicine_name,
            required_quantity=quantity,
            available_quantity=stock,
            pharmacy_name="Simulated Apollo Pharmacy, Indiranagar",
            pharmacy_id="sim_pharma_apollo_01",
            unit_price=unit_price,
            total_estimated_price=unit_price * quantity,
            source="simulated_direct_pharmacy_api",
            is_simulated=True,
            details=details,
            raw_provider_response={
                "simulation": True,
                "provider": "Apollo Pharmacy API Mock",
                "in_stock": stock >= quantity,
                "stock_count": stock,
            },
        )
