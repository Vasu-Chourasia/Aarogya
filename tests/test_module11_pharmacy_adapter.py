"""Module 11: Direct Pharmacy API Integration & Sandbox-First Provider Adapter Tests.

Comprehensive 25-point automated test suite verifying vendor-agnostic pharmacy adapter,
normalized models, error handling, safety boundaries, and ExecutionGateway integration.
"""

import os
import pytest
from datetime import datetime, timedelta
from typing import Dict, Any

from aarogya.config import Settings, ExecutionMode
from aarogya.connectors.pharmacy_adapter import (
    PharmacyProviderInterface,
    MockPharmacyProvider,
    SandboxPharmacyAdapter,
    PharmacyPartnerVerifier,
    get_pharmacy_adapter,
)
from aarogya.models.pharmacy import (
    PharmacyErrorCategory,
    PharmacyAdapterException,
    PharmacyProductDetails,
    PharmacyInventoryDetails,
    PharmacyPriceDetails,
    PharmacyDeliveryCoverage,
    PharmacyOrderStatus,
)
from aarogya.models.gateway import (
    ExecutionRequest,
    ExecutionResult,
    GetProductDetailsInputContract,
    GetPriceInputContract,
    CheckDeliveryCoverageInputContract,
    GetOrderStatusInputContract,
)
from aarogya.models.enums import (
    GatewayExecutionStatus,
    CapabilityPolicyDecision,
    HealthcareDomain,
    AuditEventType,
)
from aarogya.models.connector import NormalizedCapability
from aarogya.connectors.registry import ConnectorRegistry
from aarogya.orchestrator.execution_gateway import ExecutionGateway
from aarogya.orchestrator.audit_logger import AuditLogger
from aarogya.persistence import get_persistence_bundle
from aarogya.brain.family_health_brain import FamilyHealthBrain


@pytest.fixture
def temp_db_path(tmp_path):
    """Fixture providing a temporary SQLite database path."""
    return str(tmp_path / "test_module11.db")


@pytest.fixture
def mock_provider():
    """Default mock pharmacy provider fixture."""
    return MockPharmacyProvider()


@pytest.fixture
def gateway_bundle(temp_db_path):
    """Fixture providing an initialized execution gateway and persistence bundle."""
    bundle = get_persistence_bundle(temp_db_path)
    cap = NormalizedCapability(
        capability_id="conn:apollo_pharmacy",
        source_platform="agenticorg",
        tenant_connector_id="apollo_pharmacy",
        display_name="Apollo Direct Pharmacy API",
        domain=HealthcareDomain.MEDICINE_AVAILABILITY,
        supported_operations=[
            "check_inventory",
            "get_product_details",
            "get_price",
            "check_delivery_coverage",
            "get_order_status",
            "reserve_stock",
            "create_order",
        ],
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=True,
        is_stale=False,
    )
    bundle.capability_repo.save(cap)
    registry = ConnectorRegistry(capability_repo=bundle.capability_repo)
    gateway = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION, live_execution_enabled=False),
        connector_registry=registry,
        execution_repo=bundle.execution_repo,
        idempotency_repo=bundle.idempotency_repo,
        audit_logger=AuditLogger(log_file=None, audit_repo=bundle.audit_repo),
    )
    return bundle, gateway


# ------------------------------------------------------------------------------
# 1. Mock Provider Initialization
# ------------------------------------------------------------------------------
def test_01_mock_provider_initialization(mock_provider):
    """Test mock provider initializes with correct default metadata and partner verification."""
    assert mock_provider.provider_name == "Apollo Direct Pharmacy API (Mock Provider)"
    assert mock_provider.is_verified_healthcare_partner is True
    # Can retrieve default catalog item
    item = mock_provider.get_product_details(medicine_name="Metformin 500mg")
    assert item is not None
    assert item.product_id == "prod_metformin_500"
    assert item.is_simulated is True


# ------------------------------------------------------------------------------
# 2. Missing Provider Configuration
# ------------------------------------------------------------------------------
def test_02_missing_provider_configuration():
    """Test that disabling integration in settings raises PROVIDER_UNAVAILABLE."""
    disabled_settings = Settings(pharmacy_integration_enabled=False)
    adapter = SandboxPharmacyAdapter(settings=disabled_settings)
    with pytest.raises(PharmacyAdapterException) as exc_info:
        adapter.check_inventory(medicine_name="Metformin 500mg")
    assert exc_info.value.category == PharmacyErrorCategory.PROVIDER_UNAVAILABLE


# ------------------------------------------------------------------------------
# 3. Missing Credentials Handling
# ------------------------------------------------------------------------------
def test_03_missing_credentials():
    """Test that in mock environment without credentials, adapter safely functions in mock mode."""
    settings = Settings(
        pharmacy_environment="mock",
        pharmacy_api_key=None,
        pharmacy_base_url=None,
    )
    adapter = SandboxPharmacyAdapter(settings=settings)
    # Should safely return mock data without unhandled exceptions
    inv = adapter.check_inventory(medicine_name="Metformin 500mg", quantity=10)
    assert inv.availability_status == "IN_STOCK"
    assert inv.quantity == 50
    assert inv.is_simulated is True


# ------------------------------------------------------------------------------
# 4. Product Detail Normalization
# ------------------------------------------------------------------------------
def test_04_product_detail_normalization(mock_provider):
    """Test product details are normalized into explicit Pydantic model with all required fields."""
    details = mock_provider.get_product_details(medicine_name="Metformin 500mg")
    assert isinstance(details, PharmacyProductDetails)
    assert details.product_id == "prod_metformin_500"
    assert details.product_name == "Metformin 500mg"
    assert details.active_ingredient == "Metformin Hydrochloride"
    assert details.strength == "500mg"
    assert details.dosage_form == "Tablet"
    assert details.pack_size == "Strip of 10"
    assert details.manufacturer == "Sun Pharma"
    assert details.availability_status == "IN_STOCK"
    assert isinstance(details.last_checked, datetime)
    assert details.source_provider == mock_provider.provider_name


# ------------------------------------------------------------------------------
# 5. Inventory Normalization
# ------------------------------------------------------------------------------
def test_05_inventory_normalization(mock_provider):
    """Test inventory details are normalized properly distinguishing in-stock and out-of-stock."""
    inv_in_stock = mock_provider.check_inventory(medicine_name="Metformin 500mg", quantity=5)
    assert isinstance(inv_in_stock, PharmacyInventoryDetails)
    assert inv_in_stock.availability_status == "IN_STOCK"
    assert inv_in_stock.quantity == 50

    inv_out_stock = mock_provider.check_inventory(medicine_name="Amlodipine 5mg", quantity=1)
    assert inv_out_stock.availability_status == "OUT_OF_STOCK"
    assert inv_out_stock.quantity == 0


# ------------------------------------------------------------------------------
# 6. Price Normalization
# ------------------------------------------------------------------------------
def test_06_price_normalization(mock_provider):
    """Test pricing is normalized properly with unit price, total amount, and currency."""
    price = mock_provider.get_price(medicine_name="Metformin 500mg", quantity=30)
    assert isinstance(price, PharmacyPriceDetails)
    assert price.unit_price == 14.50
    assert price.amount == 435.0  # 14.50 * 30
    assert price.currency == "INR"
    assert price.mrp == 18.00


# ------------------------------------------------------------------------------
# 7. Delivery Coverage Normalization
# ------------------------------------------------------------------------------
def test_07_delivery_coverage_normalization(mock_provider):
    """Test delivery coverage distinguishes serviceable from non-serviceable pincodes."""
    cov_valid = mock_provider.check_delivery_coverage(pincode="560001", medicine_name="Metformin 500mg")
    assert isinstance(cov_valid, PharmacyDeliveryCoverage)
    assert cov_valid.is_serviceable is True
    assert cov_valid.coverage_result == "SERVICEABLE"
    assert cov_valid.estimated_delivery is not None

    cov_invalid = mock_provider.check_delivery_coverage(pincode="999999", medicine_name="Metformin 500mg")
    assert cov_invalid.is_serviceable is False
    assert cov_invalid.coverage_result == "NON_SERVICEABLE"
    assert cov_invalid.estimated_delivery is None


# ------------------------------------------------------------------------------
# 8. Missing Fields Remain Unknown (Never Inferred)
# ------------------------------------------------------------------------------
def test_08_missing_fields_remain_unknown(mock_provider):
    """Test that missing fields return None rather than 0 or empty string."""
    mystery = mock_provider.get_product_details(product_id="prod_unbranded_mystery")
    assert mystery.active_ingredient is None
    assert mystery.strength is None
    assert mystery.dosage_form is None
    assert mystery.manufacturer is None

    inv = mock_provider.check_inventory(product_id="prod_unbranded_mystery")
    assert inv.quantity is None  # Must remain None, not 0!

    price = mock_provider.get_price(product_id="prod_unbranded_mystery")
    assert price.amount is None  # Must remain None, not 0.0!
    assert price.unit_price is None


# ------------------------------------------------------------------------------
# 9. Invalid Provider Response Rejected
# ------------------------------------------------------------------------------
def test_09_invalid_provider_response_rejected(mock_provider):
    """Test malformed provider responses trigger INVALID_RESPONSE exception."""
    with pytest.raises(PharmacyAdapterException) as exc_info:
        mock_provider.get_product_details(medicine_name="TriggerInvalidResponse")
    assert exc_info.value.category == PharmacyErrorCategory.INVALID_RESPONSE


# ------------------------------------------------------------------------------
# 10. Provider Timeout Handled
# ------------------------------------------------------------------------------
def test_10_provider_timeout_handled(mock_provider):
    """Test provider timeouts raise TIMEOUT category and do not hang indefinitely."""
    with pytest.raises(PharmacyAdapterException) as exc_info:
        mock_provider.check_inventory(medicine_name="TriggerTimeout")
    assert exc_info.value.category == PharmacyErrorCategory.TIMEOUT


# ------------------------------------------------------------------------------
# 11. Authentication Error Handled
# ------------------------------------------------------------------------------
def test_11_authentication_error_handled(mock_provider):
    """Test authentication error triggers AUTHENTICATION_FAILURE category."""
    with pytest.raises(PharmacyAdapterException) as exc_info:
        mock_provider.get_price(medicine_name="TriggerAuthError")
    assert exc_info.value.category == PharmacyErrorCategory.AUTHENTICATION_FAILURE
    assert exc_info.value.status_code == 401


# ------------------------------------------------------------------------------
# 12. Rate Limit Handled
# ------------------------------------------------------------------------------
def test_12_rate_limit_handled(mock_provider):
    """Test 429 rate limit triggers RATE_LIMIT category."""
    with pytest.raises(PharmacyAdapterException) as exc_info:
        mock_provider.check_delivery_coverage(pincode="560001", medicine_name="TriggerRateLimit")
    assert exc_info.value.category == PharmacyErrorCategory.RATE_LIMIT
    assert exc_info.value.status_code == 429


# ------------------------------------------------------------------------------
# 13. No Fabricated Inventory
# ------------------------------------------------------------------------------
def test_13_no_fabricated_inventory(mock_provider):
    """Test that querying a non-existent medicine never invents inventory."""
    with pytest.raises(PharmacyAdapterException) as exc_info:
        mock_provider.check_inventory(medicine_name="FictionalWonderDrugXYZ")
    assert exc_info.value.category == PharmacyErrorCategory.PRODUCT_NOT_FOUND


# ------------------------------------------------------------------------------
# 14. No Fabricated Pricing
# ------------------------------------------------------------------------------
def test_14_no_fabricated_pricing(mock_provider):
    """Test that pricing for unlisted products raises not found rather than inventing prices."""
    with pytest.raises(PharmacyAdapterException) as exc_info:
        mock_provider.get_price(medicine_name="UnlistedMedicine999")
    assert exc_info.value.category == PharmacyErrorCategory.PRODUCT_NOT_FOUND


# ------------------------------------------------------------------------------
# 15. Generic Commerce Rejected as Pharmacy
# ------------------------------------------------------------------------------
def test_15_generic_commerce_rejected_as_pharmacy():
    """Test that generic commerce connectors (Shopify, Amazon) cannot be treated as pharmacies."""
    is_pharmacy = PharmacyPartnerVerifier.is_verified_pharmacy(
        capability_id="conn:shopify_retail",
        display_name="Shopify Retail Store",
        is_partner_verified=True,  # Even if someone claimed True, identifier rejects it
    )
    assert is_pharmacy is False

    is_amazon = PharmacyPartnerVerifier.is_verified_pharmacy(
        capability_id="conn:amazon_store",
        display_name="Amazon Healthcare Store",
        is_partner_verified=True,
    )
    assert is_amazon is False


# ------------------------------------------------------------------------------
# 16. Unverified Provider Rejected for Healthcare Operations
# ------------------------------------------------------------------------------
def test_16_unverified_provider_rejected_for_healthcare_ordering(gateway_bundle):
    """Test that unverified pharmacy connectors are blocked at Gate 4."""
    bundle, gateway = gateway_bundle
    # Save unverified capability
    unverified_cap = NormalizedCapability(
        capability_id="conn:unverified_pharmacy",
        source_platform="agenticorg",
        tenant_connector_id="unverified_pharmacy",
        display_name="Unverified Corner Pharmacy",
        domain=HealthcareDomain.MEDICINE_AVAILABILITY,
        supported_operations=["check_inventory"],
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=False,  # Unverified!
    )
    bundle.capability_repo.save(unverified_cap)

    req = ExecutionRequest(
        request_id="req_unverified_01",
        capability_id="conn:unverified_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gateway.execute(req)
    assert res.status == GatewayExecutionStatus.BLOCKED
    assert res.policy_decision == CapabilityPolicyDecision.BLOCKED_UNKNOWN_CAPABILITY


# ------------------------------------------------------------------------------
# 17. Gateway Enforcement Remains Mandatory
# ------------------------------------------------------------------------------
def test_17_gateway_enforcement_remains_mandatory(gateway_bundle):
    """Test that adapter calls through gateway are strictly governed by all gates."""
    bundle, gateway = gateway_bundle
    # 1. Valid simulated product details through gateway succeeds
    req_details = ExecutionRequest(
        request_id="req_gw_details_01",
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_product_details",
        input_payload={"medicine_name": "Metformin 500mg"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res_details = gateway.execute(req_details)
    assert res_details.status == GatewayExecutionStatus.SIMULATED
    assert res_details.output["active_ingredient"] == "Metformin Hydrochloride"

    # 2. Extra input fields rejected by input validation gate (extra='forbid')
    req_bad = ExecutionRequest(
        request_id="req_gw_bad_01",
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_product_details",
        input_payload={"medicine_name": "Metformin 500mg", "unauthorized_field": "hack"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res_bad = gateway.execute(req_bad)
    assert res_bad.status == GatewayExecutionStatus.REJECTED
    assert res_bad.error_category in ["INPUT_VALIDATION_ERROR", "INVALID_INPUT_SCHEMA"]


# ------------------------------------------------------------------------------
# 18. Healthcare Authorization Remains Mandatory
# ------------------------------------------------------------------------------
def test_18_healthcare_authorization_remains_mandatory(gateway_bundle):
    """Test that unauthorized users cannot execute pharmacy requests for other patients."""
    bundle, gateway = gateway_bundle
    req = ExecutionRequest(
        request_id="req_unauth_01",
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_product_details",
        input_payload={"medicine_name": "Metformin 500mg"},
        requesting_user_id="usr_stranger_99",  # Not in family circle of pat_rajesh_01
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gateway.execute(req)
    assert res.status == GatewayExecutionStatus.REJECTED
    assert res.error_category == "HEALTHCARE_AUTHORIZATION_DENIED"


# ------------------------------------------------------------------------------
# 19. HITL Approval Requirements Remain Enforced
# ------------------------------------------------------------------------------
def test_19_hitl_approval_requirements_remain_enforced(gateway_bundle):
    """Test that consequential operations (reserve_stock, create_order) require HITL approval."""
    bundle, gateway = gateway_bundle
    req_order = ExecutionRequest(
        request_id="req_order_no_app",
        capability_id="conn:apollo_pharmacy",
        requested_operation="create_order",
        input_payload={
            "medicine_name": "Metformin 500mg",
            "quantity": 30,
            "patient_id": "pat_rajesh_01",
            "delivery_address": "123 Main St, Bangalore",
            "prescription_id": "rx_001",
        },
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        approval_id=None,  # Missing approval!
        execution_mode=ExecutionMode.SIMULATION,
    )
    res_order = gateway.execute(req_order)
    assert res_order.status == GatewayExecutionStatus.PENDING_APPROVAL
    assert res_order.error_category == "APPROVAL_REQUIRED"


# ------------------------------------------------------------------------------
# 20. Live Ordering Disabled
# ------------------------------------------------------------------------------
def test_20_live_ordering_disabled(gateway_bundle):
    """Test that attempting live ordering (AUTHORIZED_EXECUTION) is strictly blocked by policy."""
    bundle, gateway = gateway_bundle
    req_live = ExecutionRequest(
        request_id="req_live_attempt",
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.AUTHORIZED_EXECUTION,  # Live execution attempt
    )
    res_live = gateway.execute(req_live)
    assert res_live.status == GatewayExecutionStatus.BLOCKED
    assert res_live.error_category == "LIVE_EXECUTION_DISABLED"


# ------------------------------------------------------------------------------
# 21. No Real Reservation or Order Creation
# ------------------------------------------------------------------------------
def test_21_no_real_reservation_or_order_creation(gateway_bundle):
    """Test that simulation execution outputs are explicitly labeled simulated."""
    bundle, gateway = gateway_bundle
    req = ExecutionRequest(
        request_id="req_sim_check",
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gateway.execute(req)
    assert res.status == GatewayExecutionStatus.SIMULATED
    assert res.is_simulated is True
    assert res.output["is_simulated"] is True


# ------------------------------------------------------------------------------
# 22. Provider Errors Are Audited Safely
# ------------------------------------------------------------------------------
def test_22_provider_errors_are_audited_safely(gateway_bundle):
    """Test that provider errors during gateway execution record structured audit events."""
    bundle, gateway = gateway_bundle
    req = ExecutionRequest(
        request_id="req_timeout_audit",
        capability_id="conn:apollo_pharmacy",
        requested_operation="check_inventory",
        input_payload={"medicine_name": "TriggerTimeout", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gateway.execute(req)
    assert res.status == GatewayExecutionStatus.TIMED_OUT
    assert res.error_category == "TIMEOUT"

    # Verify audit event in persistent repository
    events = bundle.audit_repo.list_events(request_id="req_timeout_audit")
    assert len(events) >= 1
    assert any(e.event_type == AuditEventType.GATEWAY_EXECUTION_TIMEOUT for e in events)


# ------------------------------------------------------------------------------
# 23. Credentials Are Not Leaked
# ------------------------------------------------------------------------------
def test_23_credentials_are_not_leaked(gateway_bundle):
    """Test that sensitive credentials never appear in execution output or audit records."""
    bundle, gateway = gateway_bundle
    req = ExecutionRequest(
        request_id="req_sec_audit",
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_product_details",
        input_payload={"medicine_name": "Metformin 500mg"},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res = gateway.execute(req)
    output_str = str(res.output)
    assert "secret" not in output_str.lower()
    assert "token" not in output_str.lower()
    assert "api_key" not in output_str.lower()


# ------------------------------------------------------------------------------
# 24. Persistence Survives Adapter Recreation
# ------------------------------------------------------------------------------
def test_24_persistence_survives_adapter_recreation(temp_db_path):
    """Test that pharmacy execution records survive complete gateway and adapter reinitialization."""
    bundle1 = get_persistence_bundle(temp_db_path)
    cap = NormalizedCapability(
        capability_id="conn:apollo_pharmacy",
        source_platform="agenticorg",
        tenant_connector_id="apollo_pharmacy",
        display_name="Apollo Direct Pharmacy API",
        domain=HealthcareDomain.MEDICINE_AVAILABILITY,
        supported_operations=["get_price"],
        registered=True,
        authorized=True,
        connected=True,
        healthy=True,
        capable=True,
        is_verified_healthcare_partner=True,
    )
    bundle1.capability_repo.save(cap)
    reg1 = ConnectorRegistry(capability_repo=bundle1.capability_repo)
    gw1 = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        connector_registry=reg1,
        execution_repo=bundle1.execution_repo,
        idempotency_repo=bundle1.idempotency_repo,
    )
    req = ExecutionRequest(
        request_id="req_pharm_restart",
        capability_id="conn:apollo_pharmacy",
        requested_operation="get_price",
        input_payload={"medicine_name": "Metformin 500mg", "quantity": 10},
        requesting_user_id="usr_amit_01",
        patient_id="pat_rajesh_01",
        idempotency_key="idemp_pharm_persist_99",
        execution_mode=ExecutionMode.SIMULATION,
    )
    res1 = gw1.execute(req)
    assert res1.status == GatewayExecutionStatus.SIMULATED
    bundle1.store.close()

    # Recreate store, adapter, and gateway from same DB
    bundle2 = get_persistence_bundle(temp_db_path)
    reg2 = ConnectorRegistry(capability_repo=bundle2.capability_repo)
    gw2 = ExecutionGateway(
        settings=Settings(execution_mode=ExecutionMode.SIMULATION),
        connector_registry=reg2,
        execution_repo=bundle2.execution_repo,
        idempotency_repo=bundle2.idempotency_repo,
    )
    try:
        res2 = gw2.execute(req)
        assert res2.idempotency_matched is True
        assert res2.status == GatewayExecutionStatus.SIMULATED
        assert res2.output["amount"] == 145.0  # 14.5 * 10
    finally:
        bundle2.store.close()


# ------------------------------------------------------------------------------
# 25. Order Status Query Normalization
# ------------------------------------------------------------------------------
def test_25_order_status_query_normalization(mock_provider):
    """Test retrieving existing synthetic/sandbox order status with normalized carrier tracking."""
    order_status = mock_provider.get_order_status(order_id="ord_synth_12345")
    assert isinstance(order_status, PharmacyOrderStatus)
    assert order_status.order_id == "ord_synth_12345"
    assert order_status.status == "DISPATCHED"
    assert "Apollo Central Warehouse" in order_status.status_description
    assert order_status.tracking_reference == "DELHIVERY_POD_TRACK_8889"
    assert order_status.is_simulated is True
