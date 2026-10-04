# Aarogya — AI Family Healthcare Coordinator

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Model Context Protocol](https://img.shields.io/badge/MCP-2024--11--05-blue.svg)](https://modelcontextprotocol.io/)
[![AgenticOrg](https://img.shields.io/badge/Platform-AgenticOrg-8A2BE2.svg)](https://agenticorg.ai)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **"The right healthcare need handled by the right person at the right time, with verified clinical records, explicit caregiver authorization, and confirmed outcomes."**

Aarogya is an enterprise-grade AI Family Healthcare Coordinator backend built for the **Ken Case Competition**. It orchestrates chronic care management, medicine refill tracking, doctor visit logistics, and telephony integration by pairing **AgenticOrg workflows** with a strictly governed **Model Context Protocol (MCP)** backend.

---

## 🌟 Key Capabilities

- **🧠 Family Health Brain**: In-memory verified clinical registry for chronic care (pre-seeded with patients Rajesh Kumar `pat_rajesh_01` and Sunita Kumar `pat_sunita_02`).
- **🛡️ Strictly Read-Only MCP Server**: Exposes verified context to AgenticOrg without exposing dangerous mutations (`/mcp/readonly`).
- **👥 Caregiver Relationship Resolution**: Intelligently resolves natural language relationships (*"my father"*, *"my mother"*) to patient IDs and verifies caregiver authorization permissions.
- **⚡ Multi-Agent Workflow Coordination**: Integrates with AgenticOrg's 55 A2A skills (`chat_agent`, `compliance_guard`, `ecommerce_buyer`, `notification_agent`) with Human-in-the-Loop (HITL) approval gates.
- **🔒 Enterprise Safety & Simulation Mode**: Mutating endpoints are hard-blocked in simulation mode (`AAROGYA_EXECUTION_MODE=SIMULATION`), guaranteeing zero accidental real-world transactions.

---

## 🏗️ System Architecture

```
User / Caregiver (Chat / WhatsApp / Voice)
               │
               ▼
   [AgenticOrg Platform / Aarogya 1.1]
               │
               ▼  (MCP HTTP-JSONRPC via Cloudflare / Render)
┌─────────────────────────────────────────────────────────┐
│              Aarogya Healthcare Backend                 │
│                                                         │
│   GET /mcp/readonly (Liveness & Capabilities)          │
│   POST /mcp/readonly (Authenticated Tool Invocations)   │
│                                                         │
│   ├── FamilyHealthBrain (Verified Patient Records)      │
│   ├── PolicyAuthorizationEngine (Family Circle Scope)   │
│   ├── ExecutionGateway (10 Safety Verification Gates)   │
│   └── Telephony & Pharmacy Simulation Connectors       │
└─────────────────────────────────────────────────────────┘
```

---

## 🔌 Available MCP Tools (`/mcp/readonly`)

All tools enforce strict read-only guarantees, require header authentication (`X-API-Key`), and validate caregiver permissions:

| Tool Name | Parameters | Purpose |
| :--- | :--- | :--- |
| `get_patient_medicines` | `patient_id` or `patient_name`, `user_id` | Fetches active prescriptions, dosages, current inventory, and refill thresholds. |
| `get_household_inventory` | `user_id` | Aggregates all medicine stock across every member in the caregiver's household. |
| `get_appointment` | `appointment_id`, `user_id` | Retrieves scheduled clinic visits, doctors, and logistics context. |
| `get_voice_context` | `call_id` or `patient_id` | Provides medical context and talking points for telephony voice bots (Gnani.ai). |

---

## 🚀 Quick Start (Local Setup)

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Clone and Install
```bash
git clone https://github.com/<your-username>/aarogya-backend.git
cd aarogya-backend

# Create virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Development Server
```bash
uvicorn aarogya.api.app:create_app --factory --host 127.0.0.1 --port 8000
```
- Health Check: `http://127.0.0.1:8000/api/v1/health`
- MCP Endpoint: `http://127.0.0.1:8000/mcp/readonly`

---

## ☁️ 1-Click Cloud Deployment (Render.com)

This repository includes a native [`render.yaml`](./render.yaml) blueprint:

1. Push this repository to your GitHub account.
2. In [Render Dashboard](https://dashboard.render.com), click **New +** $\rightarrow$ **Web Service**.
3. Select your repository:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn aarogya.api.app:create_app --factory --host 0.0.0.0 --port $PORT`
4. Set Environment Variables:
   - `AAROGYA_EXECUTION_MODE` = `SIMULATION`
   - `AAROGYA_LIVE_EXECUTION_ENABLED` = `false`
   - `AAROGYA_API_AUTH_ENABLED` = `true`
   - `AAROGYA_API_KEY` = `<your-chosen-secret-key>`
5. Your permanent endpoint will be:
   `https://<your-app>.onrender.com/mcp/readonly`

---

## 🧪 Running Automated Tests

Run the full suite of 15+ automated unit and integration tests:

```bash
pytest tests/test_phase23c5_mcp_readonly.py -v
```

---

## 📜 Compliance & Safety Disclosures

- **HIPAA / Consent Guard**: All patient lookups require matching authorization in the family circle.
- **Zero Real-World Mutation**: Payments and live fulfillment APIs are completely disabled during competition simulation.
- **Audit Trails**: All MCP tool queries are written to tamper-evident audit logs.
