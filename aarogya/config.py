"""Aarogya Configuration & Runtime Settings."""

import os
from enum import Enum
from typing import Optional
from pydantic_settings import BaseSettings


class ExecutionMode(str, Enum):
    """Explicit execution modes enforcing safety boundaries."""
    SIMULATION = "SIMULATION"
    CONNECTED_READ_ONLY = "CONNECTED_READ_ONLY"
    AUTHORIZED_EXECUTION = "AUTHORIZED_EXECUTION"


class Settings(BaseSettings):
    """System runtime settings loaded from environment."""
    execution_mode: ExecutionMode = ExecutionMode.SIMULATION
    
    # AgenticOrg platform
    agenticorg_enabled: bool = False
    agenticorg_api_key: Optional[str] = None
    agenticorg_base_url: str = "https://app.agenticorg.ai"
    agenticorg_grantex_token: Optional[str] = None
    agenticorg_agent_id: str = "aarogya"
    agenticorg_confidence_floor: float = 0.88
    agenticorg_deployment_status: str = "shadow"
    agenticorg_discovery_timeout_seconds: float = 10.0
    
    # Direct Pharmacy Integration (Module 3 & 11)
    pharmacy_api_base_url: Optional[str] = None
    pharmacy_api_key: Optional[str] = None
    pharmacy_timeout_seconds: float = 5.0
    pharmacy_connector_enabled: bool = False

    # Module 11: Direct Pharmacy Provider Adapter
    pharmacy_provider_name: str = "Apollo Direct (Mock Provider)"
    pharmacy_base_url: Optional[str] = None
    pharmacy_environment: str = "mock"  # "mock", "sandbox", "live"
    pharmacy_request_timeout: float = 10.0
    pharmacy_credential_ref: Optional[str] = None
    pharmacy_integration_enabled: bool = True
    pharmacy_live_operations_enabled: bool = False
    
    # Caregiver Task Backend
    task_manager_api_base_url: Optional[str] = None
    task_manager_api_key: Optional[str] = None
    task_manager_connector_enabled: bool = False
    
    # Consequential Payment & Logistics integrations
    pine_labs_merchant_id: Optional[str] = None
    pine_labs_api_key: Optional[str] = None
    payments_enabled: bool = False
    
    delhivery_api_key: Optional[str] = None
    logistics_enabled: bool = False
    
    # Module 9: Controlled Execution Gateway
    live_execution_enabled: bool = False

    # Module 10: Durable Persistence
    database_path: str = "aarogya.db"
    
    # Observability
    log_level: str = "INFO"
    audit_log_file: str = "aarogya_audit.log"
    redact_sensitive_data: bool = True

    # Phase 14: API and Voice Coordination Integration
    api_key: Optional[str] = "aarogya_secret_key_default"
    api_auth_enabled: bool = True
    gnani_webhook_secret: Optional[str] = None
    gnani_verification_enabled: bool = True
    gnani_voice_provider_mode: str = "mock"

    model_config = {
        "env_prefix": "AAROGYA_",
        "extra": "ignore",
    }


def get_settings() -> Settings:
    """Retrieve runtime settings, honoring environment overrides."""
    return Settings(
        execution_mode=ExecutionMode(
            os.getenv("AAROGYA_EXECUTION_MODE", ExecutionMode.SIMULATION.value)
        ),
        agenticorg_enabled=os.getenv("AGENTICORG_ENABLED", "false").lower() in ("true", "1", "yes"),
        agenticorg_api_key=os.getenv("AGENTICORG_API_KEY"),
        agenticorg_base_url=os.getenv("AGENTICORG_BASE_URL", "https://app.agenticorg.ai"),
        agenticorg_grantex_token=os.getenv("AGENTICORG_GRANTEX_TOKEN"),
        agenticorg_agent_id=os.getenv("AGENTICORG_AGENT_ID", "aarogya"),
        agenticorg_confidence_floor=float(os.getenv("AGENTICORG_CONFIDENCE_FLOOR", "0.88")),
        agenticorg_deployment_status=os.getenv("AGENTICORG_DEPLOYMENT_STATUS", "shadow"),
        agenticorg_discovery_timeout_seconds=float(os.getenv("AGENTICORG_DISCOVERY_TIMEOUT_SECONDS", "10.0")),
        pharmacy_api_base_url=os.getenv("PHARMACY_API_BASE_URL"),
        pharmacy_api_key=os.getenv("PHARMACY_API_KEY"),
        pharmacy_timeout_seconds=float(os.getenv("PHARMACY_TIMEOUT_SECONDS", "5.0")),
        pharmacy_connector_enabled=os.getenv("PHARMACY_CONNECTOR_ENABLED", "false").lower() == "true",
        pharmacy_provider_name=os.getenv("PHARMACY_PROVIDER_NAME", "Apollo Direct (Mock Provider)"),
        pharmacy_base_url=os.getenv("PHARMACY_BASE_URL", os.getenv("PHARMACY_API_BASE_URL")),
        pharmacy_environment=os.getenv("PHARMACY_ENVIRONMENT", "mock").lower(),
        pharmacy_request_timeout=float(os.getenv("PHARMACY_REQUEST_TIMEOUT", os.getenv("PHARMACY_TIMEOUT_SECONDS", "10.0"))),
        pharmacy_credential_ref=os.getenv("PHARMACY_CREDENTIAL_REF"),
        pharmacy_integration_enabled=os.getenv("PHARMACY_INTEGRATION_ENABLED", "true").lower() in ("true", "1", "yes"),
        pharmacy_live_operations_enabled=os.getenv("PHARMACY_LIVE_OPERATIONS_ENABLED", "false").lower() in ("true", "1", "yes"),
        task_manager_api_base_url=os.getenv("TASK_MANAGER_API_BASE_URL"),
        task_manager_api_key=os.getenv("TASK_MANAGER_API_KEY"),
        task_manager_connector_enabled=os.getenv("TASK_MANAGER_CONNECTOR_ENABLED", "false").lower() == "true",
        pine_labs_merchant_id=os.getenv("PINE_LABS_MERCHANT_ID"),
        pine_labs_api_key=os.getenv("PINE_LABS_API_KEY"),
        payments_enabled=os.getenv("PAYMENTS_ENABLED", "false").lower() == "true",
        delhivery_api_key=os.getenv("DELHIVERY_API_KEY"),
        logistics_enabled=os.getenv("LOGISTICS_ENABLED", "false").lower() == "true",
        live_execution_enabled=os.getenv("AAROGYA_LIVE_EXECUTION_ENABLED", "false").lower() in ("true", "1", "yes"),
        database_path=os.getenv("AAROGYA_DATABASE_PATH", os.getenv("DATABASE_PATH", "aarogya.db")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        audit_log_file=os.getenv("AUDIT_LOG_FILE", "aarogya_audit.log"),
        redact_sensitive_data=os.getenv("REDACT_SENSITIVE_DATA", "true").lower() == "true",
        api_key=os.getenv("AAROGYA_API_KEY", "aarogya_secret_key_default"),
        api_auth_enabled=os.getenv("AAROGYA_API_AUTH_ENABLED", "true").lower() in ("true", "1", "yes"),
        gnani_webhook_secret=os.getenv("GNANI_WEBHOOK_SECRET"),
        gnani_verification_enabled=os.getenv("GNANI_VERIFICATION_ENABLED", "true").lower() in ("true", "1", "yes"),
        gnani_voice_provider_mode=os.getenv("GNANI_VOICE_PROVIDER_MODE", "mock").lower(),
    )
