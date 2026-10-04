"""Model Context Protocol (MCP) Interface for Aarogya Healthcare Coordination Platform.

Exposes authorized appointment capabilities as MCP tools compliant with
the Model Context Protocol (2024-11-05) and directly compatible with AgenticOrg.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Dict, Any, List, Union
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...models.appointment import (
    AppointmentRequest,
    AppointmentRecord,
    AppointmentSlotApprovalRequest,
    ClinicInfo,
    DoctorInfo,
)
from ...models.voice import VoiceContextResponse
from ...workflows.appointment_coordination import AppointmentCoordinationWorkflow
from ..security import get_current_user_or_api_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Model Context Protocol (MCP)"])


def get_workflow(request: Request) -> AppointmentCoordinationWorkflow:
    """Retrieve the AppointmentCoordinationWorkflow from application state."""
    if hasattr(request.app.state, "appointment_workflow") and request.app.state.appointment_workflow:
        return request.app.state.appointment_workflow
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Appointment coordination workflow service unavailable.",
    )


# ------------------------------------------------------------------------------
# MCP Canonical Tool Schemas
# ------------------------------------------------------------------------------
MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "create_appointment",
        "description": "Create an authorized appointment coordination request and initiate clinic slot discovery. Rejects medical emergencies immediately with urgent guidance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient identifier"},
                "requesting_user_id": {"type": "string", "description": "User requesting the coordination"},
                "clinic_name": {"type": "string", "description": "Name of the clinic or hospital facility"},
                "preferred_date": {"type": "string", "description": "Target appointment date (YYYY-MM-DD)"},
                "clinic_id": {"type": "string", "description": "Optional clinic ID"},
                "doctor_name": {"type": "string", "description": "Optional preferred doctor name"},
                "specialization": {"type": "string", "description": "Optional medical specialization"},
                "preferred_time": {"type": "string", "description": "Optional preferred time window (e.g. morning, 10:00)"},
                "reason_for_visit": {"type": "string", "description": "High-level non-sensitive visit reason (e.g. routine checkup)"},
                "idempotency_key": {"type": "string", "description": "Unique key to prevent duplicate booking requests"},
            },
            "required": ["patient_id", "requesting_user_id", "clinic_name", "preferred_date"],
        },
    },
    {
        "name": "get_appointment",
        "description": "Retrieve appointment details permitted by family circle authorization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string", "description": "Unique appointment identifier"},
                "user_id": {"type": "string", "description": "Requesting family user ID for authorization check"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "get_voice_context",
        "description": "Retrieve non-sensitive, authorized minimal context needed for voice clinic coordination. Excludes sensitive clinical history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string", "description": "Unique appointment identifier"},
                "user_id": {"type": "string", "description": "Requesting family user ID for authorization check"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "approve_appointment_slot",
        "description": "Explicitly approve an offered clinic slot to confirm booking. Autonomous approval is forbidden; requires authorized caregiver.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string", "description": "Unique appointment identifier"},
                "approving_user_id": {"type": "string", "description": "Caregiver user ID authorizing the booking"},
                "slot_id": {"type": "string", "description": "Offered slot ID to approve and book"},
                "approval_notes": {"type": "string", "description": "Optional approval notes"},
                "idempotency_key": {"type": "string", "description": "Unique key to prevent duplicate approvals"},
            },
            "required": ["appointment_id", "approving_user_id", "slot_id"],
        },
    },
]


# ------------------------------------------------------------------------------
# Request / Response Schemas
# ------------------------------------------------------------------------------
class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class McpDirectCallRequest(BaseModel):
    name: str
    arguments: Optional[Dict[str, Any]] = Field(default_factory=dict)


class McpDirectCallResponse(BaseModel):
    name: str
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None


# ------------------------------------------------------------------------------
# Tool Dispatcher
# ------------------------------------------------------------------------------
def execute_mcp_tool(
    name: str,
    args: Dict[str, Any],
    workflow: AppointmentCoordinationWorkflow,
) -> Tuple[bool, Any, Optional[str]]:
    """Execute an MCP tool against existing workflow logic with fail-closed safety."""
    if name == "create_appointment":
        patient_id = str(args.get("patient_id") or "").strip()
        requesting_user_id = str(args.get("requesting_user_id") or "").strip()
        clinic_name = str(args.get("clinic_name") or "").strip()
        preferred_date = str(args.get("preferred_date") or "").strip()

        if not patient_id or not requesting_user_id or not clinic_name or not preferred_date:
            return False, None, "Missing required arguments: patient_id, requesting_user_id, clinic_name, preferred_date."

        clinic_id = str(args.get("clinic_id") or f"clinic_{clinic_name.lower().replace(' ', '_')}").strip()
        clinic = ClinicInfo(clinic_id=clinic_id, clinic_name=clinic_name)

        doctor = None
        if args.get("doctor_name"):
            doctor = DoctorInfo(
                doctor_name=str(args["doctor_name"]),
                specialization=str(args.get("specialization")) if args.get("specialization") else None,
            )

        req = AppointmentRequest(
            patient_id=patient_id,
            requesting_user_id=requesting_user_id,
            clinic=clinic,
            doctor=doctor,
            preferred_date=preferred_date,
            preferred_time=args.get("preferred_time"),
            reason_for_visit=args.get("reason_for_visit"),
            idempotency_key=args.get("idempotency_key"),
        )
        success, message, record = workflow.initiate_coordination(req)
        if not success:
            return False, None, message
        return True, record.model_dump(mode="json"), None

    elif name == "get_appointment":
        appt_id = str(args.get("appointment_id") or "").strip()
        if not appt_id:
            return False, None, "Missing required argument: appointment_id."

        rec = workflow._get_record(appt_id)
        if not rec:
            return False, None, f"Appointment '{appt_id}' not found."

        user_id = str(args.get("user_id") or rec.requesting_user_id)
        is_auth, reason = workflow.policy_engine.authorize_request(
            user_id=user_id,
            patient_id=rec.patient_id,
            action="view_records",
        )
        if not is_auth:
            return False, None, f"Access denied: {reason}"
        return True, rec.model_dump(mode="json"), None

    elif name == "get_voice_context":
        appt_id = str(args.get("appointment_id") or "").strip()
        if not appt_id:
            return False, None, "Missing required argument: appointment_id."

        rec = workflow._get_record(appt_id)
        if not rec:
            return False, None, f"Appointment '{appt_id}' not found."

        user_id = str(args.get("user_id") or rec.requesting_user_id)
        success, message, context = workflow.get_voice_context(appt_id, user_id)
        if not success:
            return False, None, message
        return True, context.model_dump(mode="json"), None

    elif name == "approve_appointment_slot":
        appt_id = str(args.get("appointment_id") or "").strip()
        approving_user_id = str(args.get("approving_user_id") or "").strip()
        slot_id = str(args.get("slot_id") or "").strip()

        if not appt_id or not approving_user_id or not slot_id:
            return False, None, "Missing required arguments: appointment_id, approving_user_id, slot_id."

        req = AppointmentSlotApprovalRequest(
            appointment_id=appt_id,
            approving_user_id=approving_user_id,
            slot_id=slot_id,
            approval_notes=args.get("approval_notes"),
            idempotency_key=args.get("idempotency_key"),
        )
        success, message, record = workflow.approve_and_book_slot(req)
        if not success:
            return False, None, message
        return True, record.model_dump(mode="json"), None

    else:
        return False, None, f"Unknown tool: '{name}'"


class McpLivenessResponse(BaseModel):
    """Minimal, non-sensitive MCP server liveness payload."""
    status: str = "ready"
    server: str = "aarogya-coordination-api"
    version: str = "1.0.0"
    protocol_version: str = "2024-11-05"
    transport: str = "http-jsonrpc"
    capabilities: Dict[str, Any] = Field(default_factory=lambda: {"tools": {"listChanged": False}})


# ------------------------------------------------------------------------------
# MCP Liveness & Handshake Probe Endpoint (GET /mcp and HEAD /mcp)
# ------------------------------------------------------------------------------
@router.get(
    "/mcp",
    response_model=McpLivenessResponse,
    summary="Model Context Protocol (MCP) Liveness Probe",
)
@router.head(
    "/mcp",
    summary="Model Context Protocol (MCP) Liveness HEAD Probe",
)
def get_mcp_liveness() -> McpLivenessResponse:
    """Lightweight liveness probe for registration crawlers and discovery pings.
    
    Returns non-sensitive protocol metadata without exposing business data,
    secrets, patient records, or executing operations.
    """
    return McpLivenessResponse()


# ------------------------------------------------------------------------------
# Standard MCP JSON-RPC 2.0 Endpoint (POST /mcp)
# ------------------------------------------------------------------------------
@router.post(
    "/mcp",
    response_model=JsonRpcResponse,
    summary="Model Context Protocol (MCP) JSON-RPC 2.0 Endpoint",
)
def handle_mcp_jsonrpc(
    rpc_request: JsonRpcRequest,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> JsonRpcResponse:
    """Standard JSON-RPC 2.0 entrypoint for MCP agents and AgenticOrg."""
    method = rpc_request.method
    req_id = rpc_request.id
    params = rpc_request.params or {}

    if method == "initialize":
        return JsonRpcResponse(
            id=req_id,
            result={
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "aarogya-coordination-api",
                    "version": "1.0.0",
                },
            },
        )

    elif method in ("notifications/initialized", "initialized"):
        return JsonRpcResponse(id=req_id, result={"status": "ready"})

    elif method == "ping":
        return JsonRpcResponse(id=req_id, result={})

    elif method in ("tools/list", "tools_list"):
        return JsonRpcResponse(
            id=req_id,
            result={"tools": MCP_TOOLS},
        )

    elif method in ("tools/call", "tools_call"):
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}

        if not tool_name:
            return JsonRpcResponse(
                id=req_id,
                error={"code": -32602, "message": "Invalid params: 'name' is required."},
            )

        success, output, error_msg = execute_mcp_tool(tool_name, arguments, workflow)

        if success:
            return JsonRpcResponse(
                id=req_id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(output, default=str),
                        }
                    ],
                    "isError": False,
                },
            )
        else:
            return JsonRpcResponse(
                id=req_id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": error_msg or "Tool execution failed.",
                        }
                    ],
                    "isError": True,
                },
            )

    else:
        return JsonRpcResponse(
            id=req_id,
            error={
                "code": -32601,
                "message": f"Method '{method}' not found.",
            },
        )


# ------------------------------------------------------------------------------
# Direct REST Endpoints for AgenticOrg SDK Compatibility
# ------------------------------------------------------------------------------
@router.get(
    "/mcp/tools",
    summary="List available MCP tools (REST)",
)
def list_mcp_tools_rest(
    _: str = Depends(get_current_user_or_api_client),
) -> Dict[str, Any]:
    """Expose tool metadata directly to AgenticOrg SDK client (client.mcp.tools())."""
    return {"tools": MCP_TOOLS}


@router.post(
    "/mcp/call",
    response_model=McpDirectCallResponse,
    summary="Call an MCP tool (REST)",
)
def call_mcp_tool_rest(
    call_req: McpDirectCallRequest,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> McpDirectCallResponse:
    """Execute tool directly for AgenticOrg SDK client (client.mcp.call())."""
    success, output, error_msg = execute_mcp_tool(
        call_req.name,
        call_req.arguments or {},
        workflow,
    )
    return McpDirectCallResponse(
        name=call_req.name,
        success=success,
        output=output,
        error=error_msg,
    )
