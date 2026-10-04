"""Module 11: Direct Pharmacy API Normalized Models and Error Categories."""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class PharmacyErrorCategory(str, Enum):
    """Structured categories for pharmacy provider failures."""
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    AUTHORIZATION_FAILURE = "AUTHORIZATION_FAILURE"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    INVENTORY_UNAVAILABLE = "INVENTORY_UNAVAILABLE"
    UNKNOWN_PROVIDER_OUTCOME = "UNKNOWN_PROVIDER_OUTCOME"
    LIVE_ORDERING_DISABLED = "LIVE_ORDERING_DISABLED"
    UNVERIFIED_PROVIDER = "UNVERIFIED_PROVIDER"


class PharmacyAdapterException(Exception):
    """Structured exception raised by pharmacy adapters with explicit failure category."""

    def __init__(
        self,
        category: PharmacyErrorCategory,
        details: str,
        status_code: Optional[int] = None,
        provider_name: Optional[str] = None,
    ):
        super().__init__(f"[{category.value}] {details}")
        self.category = category
        self.details = details
        self.status_code = status_code
        self.provider_name = provider_name


# ------------------------------------------------------------------------------
# Normalized Provider Response Models
# (Never infer missing fields: None indicates unprovided, NOT 0 or False)
# ------------------------------------------------------------------------------

class PharmacyProductDetails(BaseModel):
    """Normalized medicine product details from pharmacy catalog."""
    product_id: str
    product_name: str
    active_ingredient: Optional[str] = None
    strength: Optional[str] = None
    dosage_form: Optional[str] = None
    pack_size: Optional[str] = None
    manufacturer: Optional[str] = None
    availability_status: str = "UNKNOWN"
    last_checked: datetime = Field(default_factory=datetime.utcnow)
    source_provider: str
    is_simulated: bool = False


class PharmacyInventoryDetails(BaseModel):
    """Normalized stock inventory details from pharmacy provider."""
    product_id: str
    medicine_name: Optional[str] = None
    availability_status: str  # "IN_STOCK", "OUT_OF_STOCK", "LOW_STOCK", "UNKNOWN"
    quantity: Optional[int] = None  # None if quantity not explicitly provided by API!
    inventory_timestamp: datetime = Field(default_factory=datetime.utcnow)
    provider_reference: str
    is_simulated: bool = False


class PharmacyPriceDetails(BaseModel):
    """Normalized pricing details from pharmacy provider."""
    product_id: str
    medicine_name: Optional[str] = None
    amount: Optional[float] = None  # None if price not explicitly returned!
    currency: str = "INR"
    unit_price: Optional[float] = None
    mrp: Optional[float] = None
    price_timestamp: datetime = Field(default_factory=datetime.utcnow)
    provider_reference: str
    is_simulated: bool = False


class PharmacyDeliveryCoverage(BaseModel):
    """Normalized delivery serviceability and estimated timeframe."""
    pincode: str
    is_serviceable: bool
    coverage_result: str  # "SERVICEABLE", "NON_SERVICEABLE", "RESTRICTED", "UNKNOWN"
    estimated_delivery: Optional[str] = None  # None if provider did not return estimated time!
    delivery_partner: Optional[str] = None
    provider_reference: str
    is_simulated: bool = False


class PharmacyOrderStatus(BaseModel):
    """Normalized status for synthetic or sandbox order reference."""
    order_id: str
    status: str  # "ORDER_PLACED", "DISPATCHED", "DELIVERED", "CANCELLED", "UNKNOWN"
    status_description: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    tracking_reference: Optional[str] = None
    provider_reference: str
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    is_simulated: bool = False
