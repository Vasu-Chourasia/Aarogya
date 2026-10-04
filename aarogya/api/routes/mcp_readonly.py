"""Model Context Protocol (MCP) Read-Only Interface for Aarogya Healthcare Coordination Platform.

Exposes strictly read-only appointment and clinic voice context tools compliant with
the Model Context Protocol (2024-11-05) for safe, mutation-free AgenticOrg integration.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional, Dict, Any, List, Union, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...workflows.appointment_coordination import AppointmentCoordinationWorkflow
from ..security import get_current_user_or_api_client
from .mcp import (
    JsonRpcRequest,
    JsonRpcResponse,
    McpDirectCallRequest,
    McpDirectCallResponse,
    get_workflow,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Model Context Protocol - Read-Only (MCP)"])

# ------------------------------------------------------------------------------
# Strictly Read-Only MCP Tool Schemas
# ------------------------------------------------------------------------------
MCP_READONLY_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_appointment",
        "description": "Retrieve appointment details permitted by family circle authorization. Strictly read-only.",
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
        "description": "Retrieve non-sensitive, authorized minimal context needed for voice clinic coordination. Excludes sensitive clinical history. Strictly read-only.",
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
        "name": "get_patient_medicines",
        "description": "Retrieve verified active prescriptions, medicine plans, and current inventory levels for a patient permitted by family circle authorization. Strictly read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient identifier (e.g. 'pat_rajesh_01', 'pat_sunita_02'), full name, or relationship (e.g. 'father', 'mother', 'my father', 'my mother')",
                },
                "user_id": {
                    "type": "string",
                    "description": "Requesting family user ID for authorization check (defaults to 'usr_amit_01')",
                    "default": "usr_amit_01",
                },
                "medicine_name": {
                    "type": "string",
                    "description": "Optional specific medicine name filter (e.g. 'Thyronorm', 'Medicine X')",
                },
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_household_inventory",
        "description": "Retrieve household medicine inventory across all authorized family members for a caregiver. Strictly read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Requesting family caregiver user ID (defaults to 'usr_amit_01')",
                    "default": "usr_amit_01",
                },
            },
            "required": [],
        },
    },
]

FORBIDDEN_MUTATING_TOOLS = {
    "create_appointment": "create_appointment is a mutating tool and is strictly forbidden on this read-only endpoint.",
    "approve_appointment_slot": "approve_appointment_slot is a mutating tool and is strictly forbidden on this read-only endpoint.",
    "place_medicine_order": "place_medicine_order is a mutating tool and is strictly forbidden on this read-only endpoint.",
    "create_caregiver_task": "create_caregiver_task is a mutating tool and is strictly forbidden on this read-only endpoint.",
    "update_medicine_inventory": "update_medicine_inventory is a mutating tool and is strictly forbidden on this read-only endpoint.",
}


# ------------------------------------------------------------------------------
# Read-Only Tool Dispatcher
# ------------------------------------------------------------------------------
def execute_readonly_mcp_tool(
    name: str,
    args: Dict[str, Any],
    workflow: AppointmentCoordinationWorkflow,
) -> Tuple[bool, Any, Optional[str]]:
    """Execute an MCP tool against existing workflow logic with strict read-only enforcement."""
    # Explicit rejection of known mutating operations at the router boundary
    if name in FORBIDDEN_MUTATING_TOOLS:
        logger.warning("Attempted call to mutating tool '%s' on read-only MCP endpoint blocked.", name)
        return False, None, FORBIDDEN_MUTATING_TOOLS[name]

    if name == "get_appointment":
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

    elif name == "get_patient_medicines":
        pat_input = str(args.get("patient_id") or "").strip()
        user_id = str(args.get("user_id") or "usr_amit_01").strip() or "usr_amit_01"
        if not pat_input:
            return False, None, "Missing required argument: patient_id."

        # Resolve patient by ID, name, or relationship
        patient = workflow.brain.get_patient(pat_input)
        if not patient:
            patient = workflow.brain.resolve_patient_by_relationship(user_id, pat_input)

        if not patient:
            return False, None, f"Patient '{pat_input}' not found in Family Health Brain."

        # Check authorization with policy engine
        is_auth, reason = workflow.policy_engine.authorize_request(
            user_id=user_id,
            patient_id=patient.patient_id,
            action="check_medicine",
        )
        if not is_auth:
            return False, None, f"Access denied: {reason}"

        # Verified active prescriptions
        today = date.today()
        med_filter = str(args.get("medicine_name") or "").strip().lower()
        active_prescriptions = []
        for rx in patient.prescriptions:
            if not rx.is_verified or rx.valid_until < today:
                continue
            rx_dict = rx.model_dump(mode="json")
            if med_filter:
                matching_items = [
                    m for m in rx_dict.get("medicines", [])
                    if med_filter in m.get("medicine_name", "").lower()
                ]
                if matching_items:
                    rx_dict["medicines"] = matching_items
                    active_prescriptions.append(rx_dict)
            else:
                active_prescriptions.append(rx_dict)

        # Medicine plans and current inventory
        plans_out = []
        inventory_summary = []
        for plan in patient.medicine_plans:
            if med_filter and med_filter not in plan.medicine_name.lower():
                continue
            plans_out.append(plan.model_dump(mode="json"))
            inventory_summary.append({
                "plan_id": plan.plan_id,
                "medicine_name": plan.medicine_name,
                "strength": plan.strength,
                "dosage": plan.dosage,
                "frequency": plan.frequency,
                "current_inventory_count": plan.current_inventory_count,
                "reorder_threshold": plan.reorder_threshold,
                "reorder_recommended": plan.current_inventory_count <= plan.reorder_threshold,
                "last_refill_date": str(plan.last_refill_date) if plan.last_refill_date else None,
            })

        data = {
            "patient_id": patient.patient_id,
            "patient_name": patient.full_name,
            "gender": patient.gender,
            "chronic_conditions": patient.chronic_conditions,
            "prescriptions": active_prescriptions,
            "medicine_plans": plans_out,
            "inventory_status": inventory_summary,
        }
        return True, data, None

    elif name == "get_household_inventory":
        user_id = str(args.get("user_id") or "usr_amit_01").strip() or "usr_amit_01"

        household_records = []
        for patient in workflow.brain._patients.values():
            is_auth, _ = workflow.policy_engine.authorize_request(
                user_id=user_id,
                patient_id=patient.patient_id,
                action="check_medicine",
            )
            if is_auth:
                pat_inv = []
                for plan in patient.medicine_plans:
                    pat_inv.append({
                        "plan_id": plan.plan_id,
                        "medicine_name": plan.medicine_name,
                        "strength": plan.strength,
                        "dosage": plan.dosage,
                        "frequency": plan.frequency,
                        "current_inventory_count": plan.current_inventory_count,
                        "reorder_threshold": plan.reorder_threshold,
                        "reorder_recommended": plan.current_inventory_count <= plan.reorder_threshold,
                        "last_refill_date": str(plan.last_refill_date) if plan.last_refill_date else None,
                    })
                household_records.append({
                    "patient_id": patient.patient_id,
                    "patient_name": patient.full_name,
                    "chronic_conditions": patient.chronic_conditions,
                    "inventory": pat_inv,
                })

        if not household_records:
            return False, None, f"No authorized patient records found for user '{user_id}'."

        return True, {
            "requesting_caregiver_id": user_id,
            "authorized_patients_count": len(household_records),
            "household_inventory": household_records,
        }, None

    else:
        return False, None, f"Unknown tool: '{name}'. Only strictly read-only tools ('get_appointment', 'get_voice_context', 'get_patient_medicines', 'get_household_inventory') are available on this endpoint."


# ------------------------------------------------------------------------------
# Read-Only Liveness DTO
# ------------------------------------------------------------------------------
class ReadonlyMcpLivenessResponse(BaseModel):
    """Minimal, non-sensitive MCP read-only server liveness payload."""
    status: str = "ready"
    server: str = "aarogya-coordination-api-readonly"
    version: str = "1.0.0"
    protocol_version: str = "2024-11-05"
    transport: str = "http-jsonrpc"
    mode: str = "strictly_read_only"
    capabilities: Dict[str, Any] = Field(default_factory=lambda: {"tools": {"listChanged": False}})
    tool_count: int = len(MCP_READONLY_TOOLS)


# ------------------------------------------------------------------------------
# Liveness & Handshake Probes (GET and HEAD /mcp/readonly)
# ------------------------------------------------------------------------------
@router.get(
    "/mcp/readonly",
    response_model=ReadonlyMcpLivenessResponse,
    summary="Read-Only Model Context Protocol (MCP) Liveness Probe",
)
@router.head(
    "/mcp/readonly",
    summary="Read-Only Model Context Protocol (MCP) Liveness HEAD Probe",
)
def get_readonly_mcp_liveness() -> ReadonlyMcpLivenessResponse:
    """Lightweight liveness probe for registration crawlers and discovery pings."""
    return ReadonlyMcpLivenessResponse()


# ------------------------------------------------------------------------------
# Standard MCP JSON-RPC 2.0 Endpoint (POST /mcp/readonly)
# ------------------------------------------------------------------------------
@router.post(
    "/mcp/readonly",
    response_model=JsonRpcResponse,
    summary="Model Context Protocol (MCP) Read-Only JSON-RPC 2.0 Endpoint",
)
def handle_readonly_mcp_jsonrpc(
    rpc_request: JsonRpcRequest,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> JsonRpcResponse:
    """Standard JSON-RPC 2.0 entrypoint for MCP agents restricted to read-only tools."""
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
                    "name": "aarogya-coordination-api-readonly",
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
            result={"tools": MCP_READONLY_TOOLS},
        )

    elif method in ("tools/call", "tools_call"):
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}

        if not tool_name:
            return JsonRpcResponse(
                id=req_id,
                error={"code": -32602, "message": "Invalid params: 'name' is required."},
            )

        success, output, error_msg = execute_readonly_mcp_tool(tool_name, arguments, workflow)

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
# Direct REST Endpoints for Read-Only AgenticOrg Compatibility
# ------------------------------------------------------------------------------
@router.get(
    "/mcp/readonly/tools",
    summary="List available Read-Only MCP tools (REST)",
)
def list_readonly_mcp_tools_rest(
    _: str = Depends(get_current_user_or_api_client),
) -> Dict[str, Any]:
    """Expose read-only tool metadata directly to AgenticOrg SDK client."""
    return {"tools": MCP_READONLY_TOOLS}


@router.post(
    "/mcp/readonly/call",
    response_model=McpDirectCallResponse,
    summary="Call a Read-Only MCP tool (REST)",
)
def call_readonly_mcp_tool_rest(
    call_req: McpDirectCallRequest,
    workflow: AppointmentCoordinationWorkflow = Depends(get_workflow),
    _: str = Depends(get_current_user_or_api_client),
) -> McpDirectCallResponse:
    """Execute tool directly for AgenticOrg SDK client with read-only enforcement."""
    success, output, error_msg = execute_readonly_mcp_tool(
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
