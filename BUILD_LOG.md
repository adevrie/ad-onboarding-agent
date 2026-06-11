# BUILD LOG — MOCKCO Onboarding/Offboarding Agent
**Course:** AI 502 · Project 3
**Author:** Andrew DeVries

---

## Project Overview

An agentic AI system that automates employee onboarding and offboarding workflows in a simulated hybrid enterprise IT environment modeled on a real production domain (MOCKCO). The core design requirement: **all workflow decisions must come from the LLM** — no hardcoded step sequences in Python. The model reads MCP-style tool descriptions and reasons about what to call, in what order, for each unique request.

The simulation is grounded in real sysadmin domain knowledge: location-based OUs, role-based M365 license tiers, separate admin accounts for IT staff, hybrid Exchange mailbox provisioning, and distinct resignation vs. termination offboarding logic.

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
| LLM | `claude-opus-4-8` | Most capable model for multi-step reasoning and tool use |
| Thinking mode | `adaptive` | Claude decides when and how much extended reasoning to apply; better for varied IT workflows than forcing thinking on every turn |
| Tool loop | Manual (not framework-managed) | Fine-grained control over logging, per-call tracing, and future approval gates |
| Tool format | Anthropic `tools=` parameter with `input_schema` | MCP-style JSON Schema passed directly to API — model reads descriptions to decide when and how to call each tool |
| State | In-memory mutable dict (`_AD_USERS_DB`) | Tool effects persist within a session so create → verify → offboard chains work correctly |
| Entry point | CLI (`main.py`) | Simple interactive loop for development and demo |

---

### Files Created

| File | Purpose |
|---|---|
| `tools.py` | 9 MCP tool schemas + handler functions + dispatcher |
| `agent.py` | `OnboardingAgent` class with agentic loop |
| `prompts.py` | System prompt: IT agent persona, workflow rules, safety constraints |
| `main.py` | Interactive CLI entry point |
| `requirements.txt` | `anthropic`, `python-dotenv`, `streamlit` |
| `.env.example` | Template for API key configuration |

---

### Initial MCP Tool Definitions (`tools.py` v1)

9 tools defined in `TOOL_DEFINITIONS` — each with `name`, `description`, and `input_schema` (JSON Schema). Passed verbatim to the Anthropic API `tools=` parameter. The model reads these descriptions to decide which tools to call and when.

| Tool | Required Inputs | Purpose |
|---|---|---|
| `get_onboarding_template` | `role` | Returns phased onboarding checklist for a job role |
| `get_department_policies` | `department` | Returns standard groups, license tier, software, compliance requirements |
| `create_ad_user` | `first_name`, `last_name`, `department`, `job_title` | Creates AD account, returns username + temp password |
| `assign_ad_groups` | `username`, `groups` | Adds user to AD security/distribution groups |
| `provision_exchange_mailbox` | `username` | Enables hybrid Exchange mailbox |
| `assign_m365_license` | `username`, `license_type` | Assigns M365 SKU; validates mailbox exists first |
| `disable_ad_user` | `username`, `reason` | Disables account, terminates sessions, moves to Disabled OU |
| `revoke_access` | `username` | Removes groups, revokes VPN, invalidates M365 sessions, blocks forwarding |
| `get_user_status` | `username` | Returns full account state — used for verification and offboarding lookups |

**Dependency chain enforced by tool descriptions, not Python logic:**
```
create_ad_user → assign_ad_groups → provision_exchange_mailbox → assign_m365_license
```

The model is told in each tool's description what it depends on. For example, `assign_m365_license` states "Requires Exchange mailbox to already be provisioned." The Python code does not enforce this order — the LLM reasons about it.

---

### Initial System Prompt — Version 1 (`prompts.py` v1)

The first system prompt used a generic enterprise environment called "Contoso Corporation." Key sections:

- Agent role as IT orchestrator for CONTOSO domain
- Generic hybrid Exchange / AAD Connect / Intune environment
- Onboarding dependency order guidance
- Emergency offboarding keyword detection
- Safety rules (verify before destructive actions, never skip dependencies)
- Response format: Summary → Actions Taken → Outstanding Items → Credentials

**Limitation identified:** The v1 prompt and mock data used a generic fictional environment with no real sysadmin specificity. Department-based OUs, generic group names, and invented seed users meant the model was reasoning about a generic IT environment rather than a domain-specific one. This weakened the grounding rubric item and made the project feel like a tutorial rather than a real-world application.

---

### Initial Mock Data — v1 (`tools.py` v1)

**Departments:** IT, Finance, HR, Engineering, Sales

**Seed users:**
- `jsmith` — Engineering, Software Engineer
- `mwilliams` — Finance, Finance Manager
- `rjohnson` — IT, System Administrator

**OU structure:** Department-based (`OU=Engineering,OU=Departments,DC=contoso,DC=local`)

**Email format:** `username@contoso.com`

---

### Tool Test Results (v1)

All 9 tools passed functional smoke tests against the initial Contoso mock data:

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

State mutation verified: user created by `create_ad_user` was visible to subsequent tool calls within the same session.

---

## Session 2 — 2026-06-11

### Goals
- Rebuild mock data layer to reflect a real hybrid enterprise domain (MOCKCO)
- Update system prompt with domain-specific grounding
- Run first live agent test against the real Claude API
- Document bugs found and fixes applied

---

### Decision: Replace Generic Contoso Environment with MOCKCO

**Problem with v1:** The initial environment was generic — fictional company, department-based OUs, generic group names, invented users. This is the most common failure mode for projects like this: the simulation looks like AD but doesn't reflect how a real enterprise is actually structured.

**Solution:** Rebuilt the mock data layer from scratch based on the author's real production domain knowledge as a working System Administrator managing a hybrid on-premises AD environment. The MOCKCO environment reflects actual enterprise patterns:

- **Location-based OU structure** — real enterprises with multiple sites organize OUs by location, not department. MOCKCO has four sites: Holland, Grand Rapids (HQ), Kalamazoo, Big Rapids.
- **Dual accounts for IT staff** — privileged users have a standard account (`jdoe`) for daily use and a separate admin account (`jdoe-admin`) in `OU=Admins` for privileged operations. This is standard security practice in real environments.
- **Separated email and username** — username is `firstinitiallastname` (e.g. `jdoe`), but email is `firstname.lastname@mockcompany.com`. These are different fields in a real hybrid Exchange environment.
- **Role-based M365 license tiers** — E5 for executives and IT, E3 for office/engineering staff, F3 for frontline production workers, Business Premium for purchasing. This reflects real procurement patterns, not a uniform license assignment.
- **Distinct resignation vs. termination offboarding** — resignations convert the mailbox to shared with optional forwarding; terminations block forwarding immediately and trigger no-forwarding-without-approval policy.
- **Contractor handling** — contractors receive `SG-Contractors` group membership and typically F3 or no license.

---

### System Prompt — Version 2 (`prompts.py` v2)

**What changed from v1:**

| Section | v1 (Contoso) | v2 (MOCKCO) |
|---|---|---|
| Domain | `CONTOSO` / `contoso.local` | `MOCKCO` / `mockcompany.local` |
| OU structure | Department-based | Location-based (Holland, GR, Kalamazoo, Big Rapids) |
| Email format | `username@contoso.com` | `firstname.lastname@mockcompany.com` |
| License tier table | Generic descriptions | Explicit role-to-license mapping table |
| Group naming | Generic examples | MOCKCO conventions: `SG-Department-Access`, `SG-Role-Title`, `DL-GroupName` |
| IT dual accounts | Not mentioned | Explicit rule: IT roles auto-create `username-admin` in `OU=Admins` |
| Offboarding types | Emergency vs. normal | Three types: resignation, termination for cause, security incident — each with distinct behavior |
| Location requirement | Optional | Explicit safety rule: location is required before account creation |

**Why these changes matter for the rubric:**
The grounding rubric item requires the model to have access to information it could not know from pretraining alone. Generic AD knowledge (users go in OUs, groups control access) is already in Claude's training data. The MOCKCO-specific content — the four-site location structure, the dual-account IT policy, the specific license tier assignments by role, the `SM-`/`DL-`/`SG-` naming conventions — is not. That specificity is what makes this grounding rather than just system prompt boilerplate.

---

### MOCKCO Mock Data Coverage (`tools.py` v2)

**Departments (10):** IT, HR, Engineering, Quality, Maintenance, Production, Operations, Supply Chain, Logistics, Sales

**Role templates (7):** IT Admin, Process Engineer, HR Generalist, General Manager, Truck Driver, Furnace Operator, Purchasing Agent
- Each has: pre_day_one / day_one / week_one phases, background check flag, admin account flag, license tier

**Seed AD users (9):**

| Username | Name | Dept | Location | License |
|---|---|---|---|---|
| `adevries` | Andrew DeVries | IT | Grand Rapids | E5 |
| `adevries-admin` | Andrew DeVries (Admin) | IT | OU=Admins | None |
| `cthompson` | Carol Thompson | Operations | Grand Rapids | E5 |
| `bmartinez` | Brian Martinez | Engineering | Holland | E3 |
| `slopez` | Sandra Lopez | HR | Holland | E3 |
| `rwilson` | Robert Wilson | Production | Kalamazoo | F3 |
| `tpatel` | Tanya Patel | Logistics | Big Rapids | F3 |
| `mchen` | Michael Chen | Supply Chain | Grand Rapids | Business Premium |
| `jreyes-contractor` | Jose Reyes | Engineering (Contractor) | Grand Rapids | F3 |

**License inventory:** E5 (8 available/15 total), E3 (42/75), F3 (31/60), Business Premium (6/10)

---

### Bug Found and Fixed: `.title()` Department Key Lookup

**Bug:** In both `handle_create_ad_user` and `handle_get_department_policies`, department names were normalized with Python's `.title()` before looking them up in `_DEPARTMENT_POLICIES`. This worked for mixed-case names like `"Engineering"` but silently failed for all-caps department names like `"IT"` — `"IT".title()` returns `"It"`, which does not match the `"IT"` key in the dictionary.

**Symptom:** When an IT employee was onboarded, the department policy lookup returned `None`, so the admin account was never created and no IT-specific groups were assigned. The user would land in a generic OU with no privileged access setup.

**How it was found:** Manual smoke test after the MOCKCO rebuild:
```python
dept_policy = _DEPARTMENT_POLICIES.get("IT".title(), {})
# Returns {} because "IT".title() == "It", not "IT"
```

**Fix applied:** Changed both lookups to try exact match first, then fall back to `.title()`:
```python
# Before (broken for all-caps department names):
policy = _DEPARTMENT_POLICIES.get(department.strip().title())

# After (handles IT, HR, and mixed-case correctly):
policy = _DEPARTMENT_POLICIES.get(dept_stripped) or \
         _DEPARTMENT_POLICIES.get(dept_stripped.title())
```

**Verified fix:** Smoke tests confirmed `"IT"`, `"HR"`, and `"Engineering"` all resolve correctly after the change.

**Lesson:** Using `.title()` to normalize dictionary keys is fragile for domain-specific abbreviations. Exact match with fallback is more robust, or keys should be stored in a consistent case with a single normalization path.

---

### First Live Agent Run — 2026-06-11

**Request:**
```
Onboard Danniell Mayhew as an HR Generalist at Great Lakes, starting 2026-06-15, manager is fmettetal
```

**Model:** `claude-opus-4-8` with `thinking={"type": "adaptive"}`

**Agent trace (5 turns, ~38 seconds):**

| Turn | Stop Reason | Tool(s) Called | Decision |
|---|---|---|---|
| 1 | `tool_use` | `get_onboarding_template`, `get_department_policies` | Model correctly ran both lookups **in parallel** because they are independent — no dependency between them |
| 2 | `tool_use` | `create_ad_user` | After reading template + policies, model had enough context to create the account |
| 3 | `tool_use` | `assign_ad_groups`, `provision_exchange_mailbox` | Model correctly ran these **in parallel** — groups and mailbox are independent, both required before license |
| 4 | `tool_use` | `assign_m365_license` | Model waited until mailbox was confirmed provisioned before assigning license |
| 5 | `end_turn` | — | Model declared workflow complete and returned structured summary |

**Notable agent behavior observed:**

The model's reasoning trace on Turn 1 stated:
> *"I need to understand the standard onboarding steps for this role and the HR department's IT policies before creating anything. These two lookups are independent, so I'll run them together."*

This is genuine agentic reasoning — the model identified that `get_onboarding_template` and `get_department_policies` had no dependency between them and parallelized the calls. A hardcoded workflow would call them sequentially. Similarly on Turn 3, it parallelized `assign_ad_groups` and `provision_exchange_mailbox` for the same reason, then correctly waited to assign the license until the mailbox result confirmed success.

**What worked:**
- Correct tool call order (dependency chain respected without Python enforcement)
- Parallel calls where appropriate
- Correct license tier assigned (E3 for HR Generalist per MOCKCO policy)
- HR-specific groups assigned: `SG-HR-Full`, `SG-Role-HRGeneralist`, `HRIS-System-Access`, `Employee-Records-Access`, `Payroll-View`
- PII compliance and background check flagged in outstanding items
- Structured response format matched system prompt specification

**Bug found during live run:**

The agent's response included this note in Outstanding Items:
> *"Account was placed in OU=General,OU=Departments rather than a dedicated HR OU — verify this matches your OU structure if HR-specific GPOs apply."*

This was the `.title()` bug described above — at the time of the live run, the MOCKCO rebuild had not yet been applied. The department was passed as `"HR"` and `.title()` converted it to `"Hr"`, which failed the OU map lookup and fell through to the generic default. The bug was identified from this live run output and fixed in the subsequent MOCKCO tools.py rebuild.

**Input not in mock data — handled gracefully:**

`"Great Lakes"` as a location and `"fmettetal"` as a manager were not in the mock database. The agent did not crash — it passed `location="Great Lakes"` through as metadata and `manager="fmettetal"` as a string. The OU placement defaulted to `OU=General` due to the unrecognized location. In the MOCKCO rebuild, `location` is now a required parameter with explicit validation against the four valid MOCKCO sites.

---

### Prompt Iteration Summary

| Version | File | Key Changes | Reason |
|---|---|---|---|
| v1 | `prompts_v1.py` (archived) | Generic Contoso environment, department-based OUs, basic emergency detection | Initial implementation — functional but not grounded in real domain knowledge |
| v2 | `prompts.py` | MOCKCO domain, location-based OUs, explicit license tier table, group naming conventions, dual-account IT rule, three-way offboarding type distinction | Rebuilt to reflect real sysadmin environment; strengthens grounding, originality, and intellectual ownership rubric items |

---

## Status Summary

| Component | Status |
|---|---|
| `tools.py` — 9 MCP tool schemas | ✅ Complete (v2, MOCKCO) |
| `tools.py` — mocked handler functions | ✅ Complete (v2, MOCKCO) |
| `tools.py` — tool dispatcher | ✅ Complete |
| `tools.py` — `.title()` bug fix | ✅ Fixed |
| `agent.py` — agentic loop | ✅ Complete |
| `prompts.py` — system prompt v2 (MOCKCO) | ✅ Complete |
| `main.py` — CLI entry point | ✅ Complete (example requests need MOCKCO update) |
| First live agent run | ✅ Completed — trace documented above |
| Unit test suite (`test_suite.py`) | ✅ Written — pending full run against MOCKCO data |
| Streamlit UI (`app.py`) | 🔲 Not started |
| Deployment (Streamlit Cloud) | 🔲 Blocked on Streamlit UI |
| `eval/test_cases.json` | 🔲 Not started |
| README — full architecture + examples | ✅ Draft complete — needs real trace output |

---

## Pending / Next Steps

- [ ] **Build Streamlit UI** (`app.py`) — visual interface showing agent reasoning trace alongside final response; required for deployment
- [ ] **Deploy to Streamlit Cloud** — required for rubric item 1 (live URL)
- [ ] **Run full unit test suite** — `python test_suite.py --unit` against MOCKCO data; document results here
- [ ] **Run 3–4 additional agent scenarios** — emergency offboarding, IT admin onboarding (dual account), ambiguous request, status check; document results in `eval/test_cases.json`
- [ ] **Update `main.py` banner** — replace Contoso example requests with MOCKCO users (`adevries`, `bmartinez`, `slopez`, etc.)
- [ ] **Update README** — replace placeholder example traces with real output from live runs