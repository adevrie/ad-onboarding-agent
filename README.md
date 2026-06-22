# MOCKCO Onboarding Agent
### AI-Powered IT Onboarding & Offboarding Workflow Orchestrator

An agentic AI system that automates employee onboarding and offboarding workflows in a simulated hybrid enterprise IT environment modeled on a real production domain. The system uses Claude as a reasoning agent — all workflow decisions are made by the LLM, not hardcoded Python logic.

> **Live Demo:** [https://ad-app-agent-gvsu.streamlit.app/](https://ad-app-agent-gvsu.streamlit.app/)
> **Course:** AI 502 · Project 3 · Grand Valley State University

---

## What Problem This Solves

Onboarding and offboarding in a hybrid Active Directory environment involves a specific sequence of dependent steps — create the account, assign groups, provision the mailbox, assign the license — that varies by role, department, location, and urgency. Doing this manually is error-prone and slow. Doing it with a hardcoded script means every edge case (a new role, an unusual location, an emergency termination) requires a code change.

This system lets a sysadmin or HR staff member describe what they need in plain English. The agent figures out the rest — which tools to call, in what order, with what parameters — by reasoning about the request and the environment context it has been given.

---

## What This Does

A user types a natural language request:

```
Onboard Danniell Mayhew as an HR Generalist in Holland, starting 2026-06-15, manager is slopez
```

The agent autonomously works through the full provisioning chain across 5 turns:

1. Calls `get_onboarding_template` and `get_department_policies` **in parallel** (independent lookups)
2. Calls `create_ad_user` — username `dmayhew`, email `danniell.mayhew@mockcompany.com`, placed in `OU=Users,OU=Holland`
3. Calls `assign_ad_groups` and `provision_exchange_mailbox` **in parallel** (both independent of each other, both required before licensing)
4. Calls `assign_m365_license` with `Microsoft365_E3` (correct tier for HR per MOCKCO policy)
5. Returns a structured audit record with credentials and outstanding manual items

For an emergency offboarding:

```
Immediately offboard rwilson — security incident, suspected account compromise
```

The agent detects emergency keywords, **reverses the order** (revokes access first, then disables the account), passes `emergency=True` and `offboard_type="security_incident"` to the revocation tool, and triggers incident response — all without any if/else logic in Python.

---

## Why This Is Agentic

The core design requirement: **the LLM decides what to do, not the Python code.**

The Python layer provides:
- An execution loop that calls the API and dispatches `tool_use` blocks
- Tool handler functions that simulate enterprise systems
- Structured logging of every decision and result

The LLM decides:
- Which tools to call and in what order
- Which calls can be parallelized vs. which depend on prior results
- Whether the request is an emergency and how to sequence the response differently
- What information is missing before it can proceed (and what to ask)
- Whether to continue looping or declare the task complete
- How to handle partial tool failures

**The test:** If you removed Claude and replaced it with if/else logic, the system would break on any request that doesn't fit a fixed template. This agent handled a request with an unrecognized location, an unrecognized manager, and a role with no exact template match — and completed the workflow correctly without any code changes.

The parallel tool calling behavior is strong evidence of genuine reasoning: on Turn 1 of the live run, the model stated *"These two lookups are independent, so I'll run them together"* and called both `get_onboarding_template` and `get_department_policies` simultaneously. A hardcoded pipeline calls them sequentially. The model reasoned about dependency, not just sequence.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    User Interface                         │
│             (Streamlit UI / CLI — main.py)                │
└─────────────────────────┬────────────────────────────────┘
                          │ natural language request
                          ▼
┌──────────────────────────────────────────────────────────┐
│                   OnboardingAgent                         │
│                     (agent.py)                            │
│                                                           │
│  1. Send request + system prompt + tool definitions       │
│     to Claude API                                         │
│  2. If stop_reason == "tool_use":                         │
│       → dispatch to execute_tool()                        │
│       → append tool_result to history                     │
│       → loop back to step 1                               │
│  3. If stop_reason == "end_turn":                         │
│       → return final response                             │
└─────────────────────────┬────────────────────────────────┘
                          │ tool calls + results
                          ▼
┌──────────────────────────────────────────────────────────┐
│                   MCP Tool Layer                          │
│                    (tools.py)                             │
│                                                           │
│  get_onboarding_template   get_department_policies        │
│  create_ad_user            assign_ad_groups               │
│  provision_exchange_mailbox  assign_m365_license          │
│  disable_ad_user           revoke_access                  │
│  get_user_status                                          │
│                                                           │
│  All tools read/write _AD_USERS_DB (in-memory dict)       │
│  State persists across calls within a session             │
└─────────────────────────┬────────────────────────────────┘
                          │ structured JSON results
                          ▼
┌──────────────────────────────────────────────────────────┐
│              Simulated MOCKCO Environment                 │
│                                                           │
│  _AD_USERS_DB        — in-memory AD user store            │
│  _DEPARTMENT_POLICIES — groups, licenses, compliance      │
│  _ROLE_TEMPLATES     — phased onboarding checklists       │
│  _LICENSE_INVENTORY  — M365 SKU availability tracking     │
│  _LOCATION_OUS       — site to OU path mapping            │
└──────────────────────────────────────────────────────────┘
```

### Components

| File | Purpose |
|---|---|
| `agent.py` | `OnboardingAgent` class — API calls, tool execution loop, per-call logging |
| `tools.py` | 9 MCP tool schemas (JSON Schema) + handler functions + dispatcher |
| `prompts.py` | System prompt — MOCKCO environment context, workflow rules, license tiers, safety constraints |
| `main.py` | CLI entry point with interactive loop and conversation reset |
| `test_suite.py` | Unit tests (tool layer, no API) + agent integration tests |
| `requirements.txt` | Python dependencies |
| `BUILD_LOG.md` | Full development log — decisions, prompt iterations, bugs, test results |

### Model Configuration

| Setting | Value | Reason |
|---|---|---|
| Model | `claude-opus-4-8` | Best multi-step reasoning for agentic workflows |
| Thinking | `adaptive` | Claude decides when extended reasoning is needed per turn |
| Max iterations | 20 | Safety ceiling; typical workflows complete in 4–6 turns |
| Tool format | Anthropic `tools=` parameter | MCP-style JSON Schema passed directly to API |

---

## MCP Tools

Tools are defined in `TOOL_DEFINITIONS` in `tools.py` and passed to the Anthropic API `tools=` parameter on every call. The model reads the descriptions and decides when, whether, and in what order to call each one. No Python logic controls the sequence.

| Tool | Key Inputs | What It Does |
|---|---|---|
| `get_onboarding_template` | `role` | Returns phased checklist (pre_day_one, day_one, week_one) for a job role at MOCKCO |
| `get_department_policies` | `department` | Returns standard SG- groups, DL- lists, M365 license tier, required software, compliance notes |
| `create_ad_user` | `first_name`, `last_name`, `department`, `job_title`, `location` | Creates AD account; username = firstinitiallastname; email = firstname.lastname@mockcompany.com; OU placed by location; auto-creates -admin account for IT roles |
| `assign_ad_groups` | `username`, `groups[]` | Adds user to AD security groups (SG-) and distribution lists (DL-); returns per-group confirmation |
| `provision_exchange_mailbox` | `username` | Enables hybrid Exchange mailbox on EXCH-MOCKCO-01; links to Exchange Online via AAD Connect |
| `assign_m365_license` | `username`, `license_type` | Assigns M365 SKU; validates mailbox exists first; decrements license inventory |
| `disable_ad_user` | `username`, `reason` | Disables account, resets password, terminates sessions, moves to `OU=Disabled Users` |
| `revoke_access` | `username`, `offboard_type`, `emergency` | Removes all groups, revokes M365/Azure AD sessions, handles mailbox disposition per offboard type; triggers incident response if emergency=True |
| `get_user_status` | `username` | Returns full account state — status, location, OU, groups, license, mailbox, last login |

**Tool dependency chain** (enforced by tool descriptions, not Python logic):
```
create_ad_user → assign_ad_groups → provision_exchange_mailbox → assign_m365_license
```

---

## Grounding

The agent is grounded in MOCKCO-specific environment knowledge that Claude could not derive from pretraining alone. Generic Active Directory knowledge is already in the model's training data. The following is not — it is injected via the tool layer and system prompt:

**Location-based OU structure** — MOCKCO organizes OUs by site, not department. The four valid locations and their OU paths are injected as grounding data:

| Location | OU Path |
|---|---|
| Holland | `OU=Users,OU=Holland,DC=mockcompany,DC=local` |
| Grand Rapids | `OU=Users,OU=GrandRapids,DC=mockcompany,DC=local` |
| Kalamazoo | `OU=Users,OU=Kalamazoo,DC=mockcompany,DC=local` |
| Big Rapids | `OU=Users,OU=BigRapids,DC=mockcompany,DC=local` |

**Role-based M365 license tiers** — the model cannot guess which license tier a given role should receive. This mapping is injected as grounding context:

| License | MOCKCO Roles |
|---|---|
| E5 | IT Admins, General Managers, Operations Managers, Executives, Data Analysts |
| E3 | Engineers, Quality Engineers, HR Generalists, Sales Managers, QMS Coordinators |
| F3 | Furnace Operators, Truck Drivers, Forklift Techs, Die Setters, Production workers |
| Business Premium | Purchasing Agents, Production Control Managers |
| F3 or none | Contractors |

**Group naming conventions** — `SG-Department-Access`, `SG-Role-Title`, `DL-GroupName`, `SM-Department`, `RM-Location-Room` are MOCKCO-specific conventions injected into the system prompt.

**IT dual-account policy** — when an IT role is onboarded, a separate privileged account (`username-admin`) is automatically created in `OU=Admins` with no mailbox or M365 license. This is a real enterprise security pattern injected as a grounding rule.

**Offboarding distinctions** — resignation, termination for cause, and security incident each trigger different mailbox disposition and forwarding behavior per MOCKCO policy.

---

## Simulated Environment

The mock data in `tools.py` represents the MOCKCO domain (`mockcompany.local`). All data reflects real enterprise patterns from production sysadmin experience.

**Domain:** MOCKCO (`mockcompany.local`) · NetBIOS: `MOCKCO` · Email: `@mockcompany.com`

**Departments (10):** IT, HR, Engineering, Quality, Maintenance, Production, Operations, Supply Chain, Logistics, Sales

**Seed users:**

| Username | Name | Department | Location | License |
|---|---|---|---|---|
| `adevries` | Andrew DeVries | IT | Grand Rapids | E5 |
| `adevries-admin` | Andrew DeVries (Admin) | IT / OU=Admins | — | None |
| `cthompson` | Carol Thompson | Operations | Grand Rapids | E5 |
| `bmartinez` | Brian Martinez | Engineering | Holland | E3 |
| `slopez` | Sandra Lopez | HR | Holland | E3 |
| `rwilson` | Robert Wilson | Production | Kalamazoo | F3 |
| `tpatel` | Tanya Patel | Logistics | Big Rapids | F3 |
| `mchen` | Michael Chen | Supply Chain | Grand Rapids | Business Premium |
| `jreyes-contractor` | Jose Reyes | Engineering (Contractor) | Grand Rapids | F3 |

**License inventory:** E5 (8/15), E3 (42/75), F3 (31/60), Business Premium (6/10)

---

## Setup

### Prerequisites

- Python 3.11+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

### Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/adevrie/ad-onboarding-agent.git
cd ad-onboarding-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and add your key:
# ANTHROPIC_API_KEY=sk-ant-...

# 4. Run the CLI
python main.py
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `CLAUDE_MODEL` | No | Model override (default: `claude-opus-4-8`) |

### Running Tests

```bash
# Unit tests — tool layer only, no API calls, no cost (~5 seconds)
python test_suite.py --unit

# Agent integration tests — full loop, requires API key (~$0.10–0.30)
python test_suite.py --agent

# Both
python test_suite.py
```

---

## Example Interactions

### Standard Onboarding — HR Generalist

**Request:**
```
Onboard Danniell Mayhew as an HR Generalist in Holland, starting 2026-06-15, manager is slopez
```

**Agent trace (actual output, 2026-06-11):**
```
14:55:09  INFO  ── Agent Turn 1 ──
14:55:14  INFO  Model responded  stop_reason=tool_use  blocks=4
14:55:14  INFO  [AGENT REASONING] These two lookups are independent, so I'll run them together.
14:55:14  INFO  Model requested 2 tool call(s)
14:55:14  INFO  >> TOOL CALL  name=get_onboarding_template
14:55:14  INFO     INPUT  {"role": "HR Generalist"}
14:55:14  INFO     RESULT  status=OK  template_matched=True
14:55:14  INFO  >> TOOL CALL  name=get_department_policies
14:55:14  INFO     INPUT  {"department": "HR"}
14:55:14  INFO     RESULT  status=OK  license: Microsoft365_E3

14:55:21  INFO  ── Agent Turn 2 ──
14:55:21  INFO  >> TOOL CALL  name=create_ad_user
14:55:21  INFO     INPUT  {"first_name": "Danniell", "last_name": "Mayhew", "department": "HR",
                           "job_title": "HR Generalist", "location": "Holland"}
14:55:21  INFO     RESULT  status=OK  AD_USER_CREATED

14:55:27  INFO  ── Agent Turn 3 ──
14:55:27  INFO  [AGENT REASONING] Two next steps are independent — assign groups and provision
                mailbox. Running in parallel.
14:55:27  INFO  Model requested 2 tool call(s)
14:55:27  INFO  >> TOOL CALL  name=assign_ad_groups
14:55:27  INFO     RESULT  status=OK  AD_GROUPS_ASSIGNED
14:55:27  INFO  >> TOOL CALL  name=provision_exchange_mailbox
14:55:27  INFO     RESULT  status=OK  EXCHANGE_MAILBOX_PROVISIONED

14:55:32  INFO  ── Agent Turn 4 ──
14:55:32  INFO  [AGENT REASONING] Mailbox prerequisite satisfied — assigning E3 license.
14:55:32  INFO  >> TOOL CALL  name=assign_m365_license
14:55:32  INFO     RESULT  status=OK  M365_LICENSE_ASSIGNED

14:55:47  INFO  ── Agent Turn 5 ──
14:55:47  INFO  end_turn reached — workflow complete
```

**Final agent response (abbreviated):**
```
Summary
Danniell Mayhew has been successfully onboarded as an HR Generalist in Holland,
starting 2026-06-15, reporting to slopez.

Actions Taken
✅ Retrieved HR Generalist onboarding template — background check required, High clearance
✅ Retrieved HR department policies — E3 license, MFA required, PII-restricted
✅ Created AD account — dmayhew / danniell.mayhew@mockcompany.com
   OU: OU=Users,OU=Holland,DC=mockcompany,DC=local
✅ Assigned 5 groups — SG-HR-Full, SG-Role-HRGeneralist, HRIS-System-Access,
   Employee-Records-Access, Payroll-View
✅ Exchange mailbox provisioned — hybrid routing, active after AAD sync (~30 min)
✅ Microsoft 365 E3 license assigned — Teams, SharePoint, Exchange Online, Intune

Credentials
  Username:           dmayhew
  Email:              danniell.mayhew@mockcompany.com
  Temporary Password: Mockco1!271 (must change on first login)
  Domain:             MOCKCO
  Start Date:         2026-06-15

Outstanding Items
• MFA enrollment required within 24 hours
• Background check required — confirm with HR before start date
• PII and data handling policy acknowledgment required on Day 1
• ADP Workforce Now access requires HR Director approval
```

---

### Emergency Offboarding — Security Incident

**Request:**
```
Immediately offboard rwilson — security incident, suspected account compromise
```

**What the agent does differently from a normal offboarding:**

The model detects `"immediately"`, `"security incident"`, and `"suspected account compromise"` as emergency keywords from the system prompt. It calls `revoke_access` with `emergency=True` **before** `disable_ad_user` — the reverse of standard resignation offboarding. No Python code routes this differently; the model interprets the request and sequences the tools accordingly.

```
>> TOOL CALL  name=get_user_status
   RESULT  found=True, status=enabled

>> TOOL CALL  name=revoke_access        ← FIRST (emergency protocol)
   INPUT  {"username": "rwilson", "emergency": true,
           "offboard_type": "security_incident"}
   RESULT  INCIDENT_RESPONSE_TRIGGERED, priority=IMMEDIATE

>> TOOL CALL  name=disable_ad_user      ← SECOND
   INPUT  {"username": "rwilson", "reason": "Security incident"}
   RESULT  AD_USER_DISABLED, moved to OU=Disabled Users
```

---

### Status Check

**Request:**
```
What is the current status of Sandra Lopez?
```

Single tool call — `get_user_status("Sandra Lopez")` via partial name match. Returns full account state in one turn with no unnecessary tool calls.

---

## Evaluation

| Scenario | Turns | Tools Called | Result |
|---|---|---|---|
| Standard onboarding (HR Generalist, Holland) | 5 | 6 | Pass |
| IT Admin onboarding (dual account) | 5 | 6 + admin account | Pass |
| Emergency offboarding (security incident) | 3 | 3 (reversed order) | Pass |
| Normal offboarding (resignation) | 3 | 3 | Pass |
| Ambiguous request (no location given) | 1 | 0 | Pass — agent asks for location |
| Status check (existing user by full name) | 1 | 1 | Pass |
| Status check (unknown user) | 1 | 1 | Pass — error handled gracefully |

**Documented failure and fix:** First live run placed a new user in `OU=General` instead of the correct location OU due to a `.title()` normalization bug (`"IT".title() == "It"`). Identified from live run output, fixed in Session 2. See BUILD_LOG.md for details.

---

## Known Limitations

- **In-memory state only** — `_AD_USERS_DB` resets on restart. A SQLite backend would make state persistent.
- **No real system integration** — all tools are mocked. Production use would require LDAP for AD and Microsoft Graph API for M365 operations.
- **Single-session context** — no memory between conversations. Each `agent.reset()` clears history.
- **No approval gates** — destructive operations execute immediately. A production version would insert a human-approval step before irreversible actions.
- **License inventory not thread-safe** — concurrent requests in a multi-user deployment could cause count inconsistencies.
- **No future-dated offboarding** — `disable_ad_user` and `revoke_access` execute immediately when called. There is no mechanism to schedule an action for a future date (e.g. "last day is Friday"). The agent detects and flags this timing mismatch rather than silently acting early, but cannot defer execution. A production version would require a scheduling layer.

---

## Build Log

See [BUILD_LOG.md](BUILD_LOG.md) for a complete record of architectural decisions, prompt versions v1 and v2, bugs found and fixed, and all test results.

---

## License

MIT License — see [LICENSE](LICENSE) for details.