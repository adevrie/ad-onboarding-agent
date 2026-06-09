# BUILD LOG — AD Onboarding Agent
**Course:** AI 502 · Project 3
**Author:** Andrew DeVries

---

## Project Overview

An agentic AI system that automates employee onboarding and offboarding workflows in a simulated hybrid enterprise IT environment. The core design requirement: **all workflow decisions must come from the LLM** — no hardcoded step sequences in Python. The model reads MCP-style tool descriptions and reasons about what to call, in what order, for each unique request.

---

## Session 1 — 2026-06-09

### Goals
- Define project architecture and requirements
- Implement `tools.py` — all MCP tool schemas and mocked handlers
- Implement `agent.py` — the agentic LLM decision loop
- Implement `prompts.py` and `main.py`
- Verify all tools functional end-to-end

---

### Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM | `claude-opus-4-8` | Most capable model; recommended default for agentic applications |
| Thinking mode | `adaptive` | Claude decides when and how much to reason; better for multi-step IT workflows |
| Tool loop | Manual (not tool runner) | Fine-grained control; enables per-call logging, traces, and future approval gates |
| Tool format | Anthropic `tools=` parameter with `input_schema` | MCP-style JSON Schema; passed directly to API |
| State | In-memory mutable dict (`_AD_USERS_DB`) | Tool effects persist within a session (e.g., check user status after creating them) |
| Entry point | CLI (`main.py`) | Simple interactive loop for demo; Streamlit UI deferred pending approval |

---

### Files Created

| File | Lines | Purpose |
|---|---|---|
| `tools.py` | 1,011 | 9 MCP tool schemas + handler functions + dispatcher |
| `agent.py` | 207 | `OnboardingAgent` class with agentic loop |
| `prompts.py` | 64 | System prompt: IT agent persona, workflow rules, safety constraints |
| `main.py` | 90 | Interactive CLI entry point |
| `requirements.txt` | 3 | `anthropic`, `python-dotenv`, `streamlit` |
| `.env.example` | 2 | Template for API key configuration |

---

### MCP Tool Definitions (`tools.py`)

9 tools defined in `TOOL_DEFINITIONS` — each with `name`, `description`, and `input_schema` (JSON Schema). These are passed verbatim to the Anthropic API `tools=` parameter.

| Tool | Required Inputs | Purpose |
|---|---|---|
| `get_onboarding_template` | `role` | Returns phased onboarding checklist for a job role |
| `get_department_policies` | `department` | Returns standard groups, license tier, software, compliance requirements |
| `create_ad_user` | `first_name`, `last_name`, `department`, `job_title` | Creates AD account, returns username + temp password |
| `assign_ad_groups` | `username`, `groups` | Adds user to AD security groups |
| `provision_exchange_mailbox` | `username` | Enables hybrid Exchange mailbox |
| `assign_m365_license` | `username`, `license_type` | Assigns M365 SKU; validates mailbox exists first |
| `disable_ad_user` | `username`, `reason` | Disables account, terminates sessions, moves to Disabled OU |
| `revoke_access` | `username` | Removes groups, revokes VPN, invalidates M365 sessions, blocks forwarding |
| `get_user_status` | `username` | Returns full account state — used for verification and offboarding lookups |

**Dependency chain enforced by tool descriptions (not Python logic):**
```
create_ad_user → assign_ad_groups → provision_exchange_mailbox → assign_m365_license
```

---

### Mock Data Coverage (`tools.py`)

**Departments** (5): IT, Finance, HR, Engineering, Sales
- Each has: standard AD groups, required software, M365 license tier, compliance notes

**Role templates** (4): System Administrator, Software Engineer, Finance Manager, HR Coordinator
- Each has: pre-day-one / day-one / week-one phases, background check flag, security clearance level

**Seed AD users** (3): `jsmith` (Engineering), `mwilliams` (Finance), `rjohnson` (IT)
- Fully populated: groups, last login, license, mailbox size, OU path

**License inventory**: E3 (47 available), E5 (12), F3 (23), Business Premium (8)

---

### Agent Loop (`agent.py`)

Class: `OnboardingAgent`

```
user_request
    │
    ▼
messages.create(model, system_prompt, tools, history)
    │
    ├─ stop_reason == "tool_use"
    │       ├── extract tool_use blocks
    │       ├── execute_tool(name, input) → JSON result
    │       ├── append tool_result blocks to history
    │       └── loop ↑
    │
    └─ stop_reason == "end_turn"
            └── return final text response
```

Key implementation details:
- `thinking={"type": "adaptive"}` on every API call
- Full conversation history maintained across turns (required by API)
- Tool results returned as `{"type": "tool_result", "tool_use_id": ..., "content": json_string}`
- Structured logging on every turn: stop_reason, token counts, tool name/input/result
- `max_iterations=20` safety ceiling with graceful message on overflow

---

### System Prompt Design (`prompts.py`)

The `SYSTEM_PROMPT` is the primary mechanism for LLM workflow control. Key sections:

- **Environment context**: domain, Exchange hybrid topology, AAD Connect, Intune/SCCM, VPN
- **Onboarding workflow guidance**: instructs model to start with `get_onboarding_template`, then `get_department_policies`, then follow dependency order
- **Emergency offboarding detection**: keywords that trigger `revoke_access(emergency=True)` first — "security", "immediately", "terminated for cause", "compromised"
- **Safety rules**: verify before destructive actions, never skip dependency steps, escalate ambiguity
- **Response format**: Summary → Actions Taken → Outstanding Items → Credentials/Confirmation

---

### Tool Test Results

All 9 tools passed functional tests:

```
get_onboarding_template    PASS  phases: pre_day_one, day_one, week_one
get_department_policies    PASS  license: Microsoft365_E3
create_ad_user             PASS  username: schen
assign_ad_groups           PASS  assigned: 3 groups
provision_exchange_mailbox PASS  email: schen@contoso.com
assign_m365_license        PASS  license: Microsoft365_E3
get_user_status            PASS  groups: 5, mailbox: True, license assigned
disable_ad_user            PASS  new_status: disabled
revoke_access              PASS  7 revocation actions taken
```

State mutation verified: user created by `create_ad_user` was visible to subsequent tool calls in the same session.

---

### How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add API key to .env
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# 3. Start the CLI
python main.py
```

**Example requests:**
```
Onboard Sarah Chen as a Software Engineer in Engineering, starting 2026-06-16, manager is rjohnson
Immediately offboard jsmith — security incident
Check the status of Maria Williams
Onboard a new Finance Manager named David Park
```

---

## Status Summary

| Component | Status |
|---|---|
| `tools.py` — 9 MCP tool schemas | Complete |
| `tools.py` — mocked handler functions | Complete |
| `tools.py` — tool dispatcher | Complete |
| `agent.py` — agentic loop | Complete |
| `prompts.py` — system prompt | Complete |
| `main.py` — CLI entry point | Complete |
| End-to-end tool tests | Passing |
| Streamlit UI | **Pending approval** |
| Deployment | **Pending approval** |

---

## Pending / Next Steps

- [ ] **Live agent run** — execute a full onboarding request against the real API to capture trace output for submission
- [ ] **Streamlit UI** — visual interface showing agent reasoning trace alongside final response *(awaiting approval)*
- [ ] **Deployment** *(awaiting approval)*
- [ ] **README update** — expand with architecture diagram and usage examples
