"""Module 11: Direct Pharmacy API Provider Adapter & Normalization Layer.

Provides a provider-agnostic adapter architecture supporting mock and sandbox environments,
normalized data models, strict failure category classification, and partner verification.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, List

import httpx

from ..config import Settings, get_settings
from ..models.pharmacy import (
    PharmacyErrorCategory,
    PharmacyAdapterException,
    PharmacyProductDetails,
    PharmacyInventoryDetails,
    PharmacyPriceDetails,
    PharmacyDeliveryCoverage,
    PharmacyOrderStatus,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Abstract Provider Interface
# ------------------------------------------------------------------------------

class PharmacyProviderInterface(ABC):
    """Abstract interface exposing vendor-neutral read-only pharmacy operations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the pharmacy provider."""
        pass

    @property
    @abstractmethod
    def is_verified_healthcare_partner(self) -> bool:
        """Whether the provider holds verified healthcare partner accreditation."""
        pass

    @abstractmethod
    def get_product_details(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
    ) -> PharmacyProductDetails:
        """Query catalog metadata for a specific medicine."""
        pass

    @abstractmethod
    def check_inventory(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
        quantity: int = 1,
    ) -> PharmacyInventoryDetails:
        """Check real-time stock availability for a medicine."""
        pass

    @abstractmethod
    def get_price(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
        quantity: int = 1,
    ) -> PharmacyPriceDetails:
        """Query current pricing and unit cost for a medicine."""
        pass

    @abstractmethod
    def check_delivery_coverage(
        self,
        pincode: str,
        medicine_name: Optional[str] = None,
    ) -> PharmacyDeliveryCoverage:
        """Verify delivery coverage and estimated turnaround for a postal code."""
        pass

    @abstractmethod
    def get_order_status(
        self,
        order_id: str,
        patient_id: Optional[str] = None,
    ) -> PharmacyOrderStatus:
        """Retrieve tracking status for a synthetic or sandbox order."""
        pass


# ------------------------------------------------------------------------------
# Mock Pharmacy Provider (Deterministic synthetic fixture)
# ------------------------------------------------------------------------------

class MockPharmacyProvider(PharmacyProviderInterface):
    """Deterministic simulated pharmacy provider for testing and development.
    
    Clearly labeled as simulated; never fabricates data or claims live status.
    """

    def __init__(
        self,
        provider_name: str = "Apollo Direct Pharmacy API (Mock Provider)",
        is_verified_partner: bool = True,
    ):
        self._provider_name = provider_name
        self._is_verified_partner = is_verified_partner

        # Deterministic synthetic catalog
        self._catalog: Dict[str, Dict[str, Any]] = {
            "prod_metformin_500": {
                "product_id": "prod_metformin_500",
                "product_name": "Metformin 500mg",
                "active_ingredient": "Metformin Hydrochloride",
                "strength": "500mg",
                "dosage_form": "Tablet",
                "pack_size": "Strip of 10",
                "manufacturer": "Sun Pharma",
                "availability_status": "IN_STOCK",
                "stock": 50,
                "unit_price": 14.50,
                "mrp": 18.00,
                "serviceable_pincodes": ["560001", "560002", "560034", "110001", "400001", "500001"],
            },
            "prod_atorvastatin_20": {
                "product_id": "prod_atorvastatin_20",
                "product_name": "Atorvastatin 20mg",
                "active_ingredient": "Atorvastatin Calcium",
                "strength": "20mg",
                "dosage_form": "Tablet",
                "pack_size": "Strip of 15",
                "manufacturer": "Cipla Ltd",
                "availability_status": "IN_STOCK",
                "stock": 25,
                "unit_price": 42.00,
                "mrp": 50.00,
                "serviceable_pincodes": ["560001", "560002", "560034", "110001"],
            },
            "prod_amlodipine_5": {
                "product_id": "prod_amlodipine_5",
                "product_name": "Amlodipine 5mg",
                "active_ingredient": "Amlodipine Besylate",
                "strength": "5mg",
                "dosage_form": "Tablet",
                "pack_size": "Strip of 10",
                "manufacturer": "Torrent Pharma",
                "availability_status": "OUT_OF_STOCK",
                "stock": 0,
                "unit_price": 8.00,
                "mrp": 10.00,
                "serviceable_pincodes": ["560001", "110001"],
            },
            # Synthetic item testing unprovided/unknown fields (None vs 0)
            "prod_unbranded_mystery": {
                "product_id": "prod_unbranded_mystery",
                "product_name": "Unbranded Formulation",
                "active_ingredient": None,
                "strength": None,
                "dosage_form": None,
                "pack_size": None,
                "manufacturer": None,
                "availability_status": "UNKNOWN",
                "stock": None,  # Explicitly unknown quantity
                "unit_price": None,  # Explicitly unquoted price
                "mrp": None,
                "serviceable_pincodes": [],
            },
        }

        # Synthetic test orders
        self._orders: Dict[str, Dict[str, Any]] = {
            "ord_synth_12345": {
                "order_id": "ord_synth_12345",
                "status": "DISPATCHED",
                "status_description": "Order dispatched from Apollo Central Warehouse",
                "items": [{"medicine_name": "Metformin 500mg", "quantity": 30}],
                "tracking_reference": "DELHIVERY_POD_TRACK_8889",
            },
            "ord_sandbox_999": {
                "order_id": "ord_sandbox_999",
                "status": "ORDER_PLACED",
                "status_description": "Order awaiting pharmacist verification",
                "items": [{"medicine_name": "Atorvastatin 20mg", "quantity": 15}],
                "tracking_reference": None,
            },
        }

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def is_verified_healthcare_partner(self) -> bool:
        return self._is_verified_partner

    def _resolve_product(
        self, product_id: Optional[str] = None, medicine_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve item from synthetic catalog or simulate test errors."""
        name_lower = (medicine_name or "").strip().lower()

        # Error simulation triggers for testing
        if "triggertimeout" in name_lower:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.TIMEOUT,
                details="Pharmacy API request timed out after 10.0 seconds.",
                provider_name=self._provider_name,
            )
        if "triggerautherror" in name_lower:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.AUTHENTICATION_FAILURE,
                details="Provider authentication failed: invalid or expired API credentials.",
                status_code=401,
                provider_name=self._provider_name,
            )
        if "triggerratelimit" in name_lower:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.RATE_LIMIT,
                details="Rate limit exceeded for pharmacy provider API (429 Too Many Requests).",
                status_code=429,
                provider_name=self._provider_name,
            )
        if "triggerinvalidresponse" in name_lower:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.INVALID_RESPONSE,
                details="Pharmacy provider returned malformed or unparseable response payload.",
                provider_name=self._provider_name,
            )
        if "triggerproviderunavailable" in name_lower:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.PROVIDER_UNAVAILABLE,
                details="Provider service temporarily unavailable (503 Service Unavailable).",
                status_code=503,
                provider_name=self._provider_name,
            )

        # 1. Lookup by product_id
        if product_id and product_id in self._catalog:
            return self._catalog[product_id]

        # 2. Lookup by medicine_name match
        if medicine_name:
            for item in self._catalog.values():
                if name_lower in item["product_name"].lower():
                    return item

        # Not found
        target = medicine_name or product_id or "unknown"
        raise PharmacyAdapterException(
            category=PharmacyErrorCategory.PRODUCT_NOT_FOUND,
            details=f"Medicine product '{target}' was not found in pharmacy provider catalog.",
            status_code=404,
            provider_name=self._provider_name,
        )

    def get_product_details(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
    ) -> PharmacyProductDetails:
        item = self._resolve_product(product_id, medicine_name)
        return PharmacyProductDetails(
            product_id=item["product_id"],
            product_name=item["product_name"],
            active_ingredient=item.get("active_ingredient"),
            strength=item.get("strength"),
            dosage_form=item.get("dosage_form"),
            pack_size=item.get("pack_size"),
            manufacturer=item.get("manufacturer"),
            availability_status=item.get("availability_status", "UNKNOWN"),
            last_checked=datetime.utcnow(),
            source_provider=self._provider_name,
            is_simulated=True,
        )

    def check_inventory(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
        quantity: int = 1,
    ) -> PharmacyInventoryDetails:
        item = self._resolve_product(product_id, medicine_name)
        stock = item.get("stock")
        if stock is not None:
            status = "IN_STOCK" if stock >= quantity else ("LOW_STOCK" if stock > 0 else "OUT_OF_STOCK")
        else:
            status = item.get("availability_status", "UNKNOWN")

        return PharmacyInventoryDetails(
            product_id=item["product_id"],
            medicine_name=item["product_name"],
            availability_status=status,
            quantity=stock,  # None if explicitly unknown! Never fabricate!
            inventory_timestamp=datetime.utcnow(),
            provider_reference=self._provider_name,
            is_simulated=True,
        )

    def get_price(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
        quantity: int = 1,
    ) -> PharmacyPriceDetails:
        item = self._resolve_product(product_id, medicine_name)
        unit = item.get("unit_price")
        total = round(unit * quantity, 2) if unit is not None else None

        return PharmacyPriceDetails(
            product_id=item["product_id"],
            medicine_name=item["product_name"],
            amount=total,  # None if unit_price is None! Never fabricate!
            currency="INR",
            unit_price=unit,
            mrp=item.get("mrp"),
            price_timestamp=datetime.utcnow(),
            provider_reference=self._provider_name,
            is_simulated=True,
        )

    def check_delivery_coverage(
        self,
        pincode: str,
        medicine_name: Optional[str] = None,
    ) -> PharmacyDeliveryCoverage:
        # Check pincode
        pincode_clean = pincode.strip()
        is_covered = False
        item = None
        if medicine_name:
            name_lower = medicine_name.strip().lower()
            if any(trig in name_lower for trig in ["triggertimeout", "triggerautherror", "triggerratelimit", "triggerinvalidresponse", "triggerproviderunavailable"]):
                self._resolve_product(medicine_name=medicine_name)
            try:
                item = self._resolve_product(medicine_name=medicine_name)
                is_covered = pincode_clean in item.get("serviceable_pincodes", [])
            except PharmacyAdapterException as e:
                if e.category != PharmacyErrorCategory.PRODUCT_NOT_FOUND:
                    raise
                is_covered = pincode_clean in ["560001", "560002", "560034", "110001", "400001"]
        else:
            is_covered = pincode_clean in ["560001", "560002", "560034", "110001", "400001", "500001"]

        return PharmacyDeliveryCoverage(
            pincode=pincode_clean,
            is_serviceable=is_covered,
            coverage_result="SERVICEABLE" if is_covered else "NON_SERVICEABLE",
            estimated_delivery="Same-day delivery within 4-6 hours" if is_covered else None,
            delivery_partner="Apollo Local Pharmacy Courier (Simulated)" if is_covered else None,
            provider_reference=self._provider_name,
            is_simulated=True,
        )

    def get_order_status(
        self,
        order_id: str,
        patient_id: Optional[str] = None,
    ) -> PharmacyOrderStatus:
        order = self._orders.get(order_id)
        if not order:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.PRODUCT_NOT_FOUND,
                details=f"Order reference '{order_id}' was not found in provider system.",
                status_code=404,
                provider_name=self._provider_name,
            )

        return PharmacyOrderStatus(
            order_id=order["order_id"],
            status=order["status"],
            status_description=order.get("status_description"),
            items=order.get("items", []),
            tracking_reference=order.get("tracking_reference"),
            provider_reference=self._provider_name,
            last_updated=datetime.utcnow(),
            is_simulated=True,
        )


# ------------------------------------------------------------------------------
# Sandbox & HTTP Provider Adapter
# ------------------------------------------------------------------------------

class SandboxPharmacyAdapter(PharmacyProviderInterface):
    """Configurable direct pharmacy adapter connecting to a mock or HTTP sandbox provider."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        provider_name: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        environment: str = "mock",
        timeout_seconds: float = 10.0,
        is_verified_partner: bool = True,
    ):
        self.settings = settings or get_settings()
        self._provider_name = provider_name or self.settings.pharmacy_provider_name
        self.base_url = (base_url or self.settings.pharmacy_base_url or "").rstrip("/")
        self.api_key = api_key or self.settings.pharmacy_api_key
        self.environment = environment or self.settings.pharmacy_environment
        self.timeout_seconds = timeout_seconds or self.settings.pharmacy_request_timeout
        self._is_verified_partner = is_verified_partner

        # Underlying mock engine used in "mock" mode or when sandbox URL is absent
        self._mock_provider = MockPharmacyProvider(
            provider_name=self._provider_name,
            is_verified_partner=self._is_verified_partner,
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def is_verified_healthcare_partner(self) -> bool:
        return self._is_verified_partner

    def _ensure_active(self) -> None:
        """Validate configuration requirements before dispatch."""
        if not self.settings.pharmacy_integration_enabled:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.PROVIDER_UNAVAILABLE,
                details="Pharmacy integration is currently disabled in system configuration.",
                provider_name=self._provider_name,
            )

    def get_product_details(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
    ) -> PharmacyProductDetails:
        self._ensure_active()
        if self.environment == "mock" or not self.base_url:
            return self._mock_provider.get_product_details(product_id, medicine_name)

        # Real Sandbox HTTP Dispatch
        endpoint = f"{self.base_url}/v1/products/details"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params: Dict[str, Any] = {}
        if product_id:
            params["product_id"] = product_id
        if medicine_name:
            params["medicine_name"] = medicine_name

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(endpoint, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return PharmacyProductDetails(
                    product_id=data["product_id"],
                    product_name=data["product_name"],
                    active_ingredient=data.get("active_ingredient"),
                    strength=data.get("strength"),
                    dosage_form=data.get("dosage_form"),
                    pack_size=data.get("pack_size"),
                    manufacturer=data.get("manufacturer"),
                    availability_status=data.get("availability_status", "UNKNOWN"),
                    last_checked=datetime.utcnow(),
                    source_provider=self._provider_name,
                    is_simulated=False,
                )
            elif resp.status_code in (401, 403):
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.AUTHENTICATION_FAILURE,
                    details=f"Provider auth error: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
            elif resp.status_code == 404:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.PRODUCT_NOT_FOUND,
                    details=f"Product not found: {resp.text}",
                    status_code=404,
                    provider_name=self._provider_name,
                )
            elif resp.status_code == 429:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.RATE_LIMIT,
                    details=f"Rate limit exceeded: {resp.text}",
                    status_code=429,
                    provider_name=self._provider_name,
                )
            else:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.INVALID_RESPONSE,
                    details=f"Unexpected status code {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
        except httpx.TimeoutException:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.TIMEOUT,
                details=f"Request to {endpoint} timed out after {self.timeout_seconds}s",
                provider_name=self._provider_name,
            )
        except PharmacyAdapterException:
            raise
        except Exception as e:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.UNKNOWN_PROVIDER_OUTCOME,
                details=f"Network error during provider invocation: {str(e)}",
                provider_name=self._provider_name,
            )

    def check_inventory(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
        quantity: int = 1,
    ) -> PharmacyInventoryDetails:
        self._ensure_active()
        if self.environment == "mock" or not self.base_url:
            return self._mock_provider.check_inventory(product_id, medicine_name, quantity)

        endpoint = f"{self.base_url}/v1/inventory/check"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params: Dict[str, Any] = {"quantity": quantity}
        if product_id:
            params["product_id"] = product_id
        if medicine_name:
            params["medicine_name"] = medicine_name

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(endpoint, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return PharmacyInventoryDetails(
                    product_id=data["product_id"],
                    medicine_name=data.get("medicine_name"),
                    availability_status=data.get("availability_status", "UNKNOWN"),
                    quantity=data.get("available_quantity"),
                    inventory_timestamp=datetime.utcnow(),
                    provider_reference=self._provider_name,
                    is_simulated=False,
                )
            elif resp.status_code in (401, 403):
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.AUTHENTICATION_FAILURE,
                    details=f"Auth failure: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
            elif resp.status_code == 404:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.PRODUCT_NOT_FOUND,
                    details=f"Product not found: {resp.text}",
                    status_code=404,
                    provider_name=self._provider_name,
                )
            elif resp.status_code == 429:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.RATE_LIMIT,
                    details=f"Rate limit: {resp.text}",
                    status_code=429,
                    provider_name=self._provider_name,
                )
            else:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.INVALID_RESPONSE,
                    details=f"Provider error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
        except httpx.TimeoutException:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.TIMEOUT,
                details=f"Inventory query timed out after {self.timeout_seconds}s",
                provider_name=self._provider_name,
            )
        except PharmacyAdapterException:
            raise
        except Exception as e:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.UNKNOWN_PROVIDER_OUTCOME,
                details=f"Network error: {str(e)}",
                provider_name=self._provider_name,
            )

    def get_price(
        self,
        product_id: Optional[str] = None,
        medicine_name: Optional[str] = None,
        quantity: int = 1,
    ) -> PharmacyPriceDetails:
        self._ensure_active()
        if self.environment == "mock" or not self.base_url:
            return self._mock_provider.get_price(product_id, medicine_name, quantity)

        endpoint = f"{self.base_url}/v1/pricing"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params: Dict[str, Any] = {"quantity": quantity}
        if product_id:
            params["product_id"] = product_id
        if medicine_name:
            params["medicine_name"] = medicine_name

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(endpoint, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return PharmacyPriceDetails(
                    product_id=data["product_id"],
                    medicine_name=data.get("medicine_name"),
                    amount=data.get("total_amount"),
                    currency=data.get("currency", "INR"),
                    unit_price=data.get("unit_price"),
                    mrp=data.get("mrp"),
                    price_timestamp=datetime.utcnow(),
                    provider_reference=self._provider_name,
                    is_simulated=False,
                )
            elif resp.status_code in (401, 403):
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.AUTHENTICATION_FAILURE,
                    details=f"Auth error: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
            else:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.INVALID_RESPONSE,
                    details=f"Price check error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
        except httpx.TimeoutException:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.TIMEOUT,
                details=f"Pricing check timed out after {self.timeout_seconds}s",
                provider_name=self._provider_name,
            )
        except PharmacyAdapterException:
            raise
        except Exception as e:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.UNKNOWN_PROVIDER_OUTCOME,
                details=f"Network error: {str(e)}",
                provider_name=self._provider_name,
            )

    def check_delivery_coverage(
        self,
        pincode: str,
        medicine_name: Optional[str] = None,
    ) -> PharmacyDeliveryCoverage:
        self._ensure_active()
        if self.environment == "mock" or not self.base_url:
            return self._mock_provider.check_delivery_coverage(pincode, medicine_name)

        endpoint = f"{self.base_url}/v1/coverage"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params: Dict[str, Any] = {"pincode": pincode}
        if medicine_name:
            params["medicine_name"] = medicine_name

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(endpoint, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return PharmacyDeliveryCoverage(
                    pincode=pincode,
                    is_serviceable=data.get("serviceable", False),
                    coverage_result=data.get("coverage_status", "UNKNOWN"),
                    estimated_delivery=data.get("estimated_delivery"),
                    delivery_partner=data.get("delivery_partner"),
                    provider_reference=self._provider_name,
                    is_simulated=False,
                )
            else:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.INVALID_RESPONSE,
                    details=f"Coverage check failed {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
        except httpx.TimeoutException:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.TIMEOUT,
                details=f"Delivery coverage query timed out after {self.timeout_seconds}s",
                provider_name=self._provider_name,
            )
        except PharmacyAdapterException:
            raise
        except Exception as e:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.UNKNOWN_PROVIDER_OUTCOME,
                details=f"Network error: {str(e)}",
                provider_name=self._provider_name,
            )

    def get_order_status(
        self,
        order_id: str,
        patient_id: Optional[str] = None,
    ) -> PharmacyOrderStatus:
        self._ensure_active()
        if self.environment == "mock" or not self.base_url:
            return self._mock_provider.get_order_status(order_id, patient_id)

        endpoint = f"{self.base_url}/v1/orders/{order_id}/status"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(endpoint, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return PharmacyOrderStatus(
                    order_id=data["order_id"],
                    status=data["status"],
                    status_description=data.get("status_description"),
                    items=data.get("items", []),
                    tracking_reference=data.get("tracking_reference"),
                    provider_reference=self._provider_name,
                    last_updated=datetime.utcnow(),
                    is_simulated=False,
                )
            elif resp.status_code == 404:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.PRODUCT_NOT_FOUND,
                    details=f"Order '{order_id}' was not found in sandbox system.",
                    status_code=404,
                    provider_name=self._provider_name,
                )
            else:
                raise PharmacyAdapterException(
                    category=PharmacyErrorCategory.INVALID_RESPONSE,
                    details=f"Order status check failed: {resp.text}",
                    status_code=resp.status_code,
                    provider_name=self._provider_name,
                )
        except httpx.TimeoutException:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.TIMEOUT,
                details=f"Order status check timed out after {self.timeout_seconds}s",
                provider_name=self._provider_name,
            )
        except PharmacyAdapterException:
            raise
        except Exception as e:
            raise PharmacyAdapterException(
                category=PharmacyErrorCategory.UNKNOWN_PROVIDER_OUTCOME,
                details=f"Network error: {str(e)}",
                provider_name=self._provider_name,
            )


# ------------------------------------------------------------------------------
# Pharmacy Partner Accreditation & Verification
# ------------------------------------------------------------------------------

class PharmacyPartnerVerifier:
    """Validates whether a connector qualifies as an accredited healthcare pharmacy partner.
    
    Strictly distinguishes generic commerce integrations (Shopify, Amazon, retail) from
    verified clinical healthcare pharmacy partners.
    """

    GENERIC_COMMERCE_IDENTIFIERS = {
        "shopify",
        "shopify_retail",
        "amazon_store",
        "flipkart_grocery",
        "woocommerce",
        "magento",
        "generic_ecommerce",
    }

    @classmethod
    def is_verified_pharmacy(
        cls,
        capability_id: str,
        display_name: str = "",
        is_partner_verified: bool = False,
    ) -> bool:
        """Evaluate if connector qualifies for clinical pharmacy operations."""
        cap_clean = capability_id.lower()
        name_clean = display_name.lower()

        # 1. Immediately reject generic commerce connectors
        for blocked in cls.GENERIC_COMMERCE_IDENTIFIERS:
            if blocked in cap_clean or blocked in name_clean:
                logger.warning(
                    "Commerce connector '%s' rejected: generic retail platforms cannot perform clinical pharmacy operations.",
                    capability_id,
                )
                return False

        # 2. Require explicit verified partner flag
        return bool(is_partner_verified)


# ------------------------------------------------------------------------------
# Default Adapter Factory
# ------------------------------------------------------------------------------

def get_pharmacy_adapter(settings: Optional[Settings] = None) -> PharmacyProviderInterface:
    """Instantiate and return the configured pharmacy provider adapter."""
    cfg = settings or get_settings()
    return SandboxPharmacyAdapter(
        settings=cfg,
        provider_name=cfg.pharmacy_provider_name,
        base_url=cfg.pharmacy_base_url,
        api_key=cfg.pharmacy_api_key,
        environment=cfg.pharmacy_environment,
        timeout_seconds=cfg.pharmacy_request_timeout,
        is_verified_partner=True,
    )
