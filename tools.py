"""
tools.py — MCP-style tool definitions and mocked handlers.

Each entry in TOOL_DEFINITIONS is passed directly to the Anthropic API `tools=`
parameter. The LLM reads these descriptions to decide which tools to call.

Handler functions simulate realistic enterprise IT responses — they mutate
in-memory state so the agent can see the effects of its own actions (e.g.,
checking a user's status after creating them, or verifying groups were added).
"""

import json
import random
from datetime import datetime
from typing import Any


# =============================================================================
# MCP-STYLE TOOL SCHEMAS
# Format matches Anthropic tool_use spec: name, description, input_schema
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "get_onboarding_template",
        "description": (
            "Retrieve the standard onboarding checklist and required steps for a given job role. "
            "Call this first when processing any new hire request to understand what steps are required. "
            "Returns a structured template with phases (pre_day_one, day_one, week_one) and required actions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": (
                        "The job role or title of the new employee. "
                        "Examples: 'System Administrator', 'Software Engineer', 'Finance Manager', 'HR Coordinator'"
                    )
                }
            },
            "required": ["role"]
        }
    },
    {
        "name": "get_department_policies",
        "description": (
            "Retrieve IT policies, required security group memberships, software requirements, "
            "and compliance rules specific to a department. "
            "Call this to determine which AD groups, license tier, and software are standard for a department."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": (
                        "The department name. "
                        "Examples: 'IT', 'Finance', 'HR', 'Engineering', 'Sales'"
                    )
                }
            },
            "required": ["department"]
        }
    },
    {
        "name": "create_ad_user",
        "description": (
            "Create a new Active Directory user account in the on-premises CONTOSO domain. "
            "Call this after gathering all required user information. "
            "Returns the generated username (sAMAccountName), UPN, OU path, and temporary password."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {
                    "type": "string",
                    "description": "Employee's first name"
                },
                "last_name": {
                    "type": "string",
                    "description": "Employee's last name"
                },
                "department": {
                    "type": "string",
                    "description": "Department the employee belongs to"
                },
                "job_title": {
                    "type": "string",
                    "description": "Job title or role"
                },
                "manager": {
                    "type": "string",
                    "description": "Manager's full name or username (optional)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Employment start date in YYYY-MM-DD format (optional)"
                },
                "location": {
                    "type": "string",
                    "description": "Office location or 'Remote' (optional, defaults to Main Office)"
                }
            },
            "required": ["first_name", "last_name", "department", "job_title"]
        }
    },
    {
        "name": "assign_ad_groups",
        "description": (
            "Add a user to one or more Active Directory security groups. "
            "Call this after creating the AD account to grant role-based access. "
            "Returns confirmation of each group assignment and any failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "The AD username (sAMAccountName) to assign groups to"
                },
                "groups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of AD security group names to add the user to"
                }
            },
            "required": ["username", "groups"]
        }
    },
    {
        "name": "provision_exchange_mailbox",
        "description": (
            "Enable an Exchange mailbox for a user in the hybrid Exchange environment. "
            "This links the on-premises AD account to Exchange Online via AAD Connect. "
            "Must be called before assigning M365 licenses. "
            "Returns mailbox details, SMTP addresses, and expected sync time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "The AD username to enable a mailbox for"
                },
                "mailbox_type": {
                    "type": "string",
                    "enum": ["UserMailbox", "SharedMailbox", "RoomMailbox"],
                    "description": "Type of mailbox to create. Defaults to UserMailbox."
                }
            },
            "required": ["username"]
        }
    },
    {
        "name": "assign_m365_license",
        "description": (
            "Assign a Microsoft 365 license to a user, enabling cloud services. "
            "Requires Exchange mailbox to already be provisioned. "
            "Returns the license type assigned, services enabled, and remaining license count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "The AD username to assign a license to"
                },
                "license_type": {
                    "type": "string",
                    "enum": [
                        "Microsoft365_E3",
                        "Microsoft365_E5",
                        "Microsoft365_F3",
                        "Microsoft365_Business_Premium"
                    ],
                    "description": (
                        "M365 license SKU. "
                        "E5 = Security/compliance-heavy roles (IT). "
                        "E3 = Standard professional roles. "
                        "Business_Premium = Sales/field roles. "
                        "F3 = Frontline/kiosk workers."
                    )
                }
            },
            "required": ["username", "license_type"]
        }
    },
    {
        "name": "disable_ad_user",
        "description": (
            "Disable an Active Directory user account, immediately preventing login "
            "and terminating all active sessions. "
            "This is the primary action for both normal and emergency offboarding. "
            "Returns confirmation, timestamp, and new OU location."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "AD username (sAMAccountName) or full name of the user to disable"
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Reason for disabling the account. "
                        "Examples: 'Voluntary resignation', 'Contract end', 'Security incident - account compromise'"
                    )
                },
                "move_to_disabled_ou": {
                    "type": "boolean",
                    "description": "If true, moves account to the Disabled Users OU. Defaults to true."
                }
            },
            "required": ["username", "reason"]
        }
    },
    {
        "name": "revoke_access",
        "description": (
            "Revoke access for a departing or terminated user. "
            "Removes from all AD security groups, revokes VPN certificates, "
            "invalidates M365/Azure AD sessions, removes email delegations, "
            "and blocks email auto-forwarding. "
            "For security incidents, set emergency=true for immediate elevated-priority revocation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "AD username or full name of the user to revoke access for"
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "groups_only", "m365_only", "vpn_only"],
                    "description": "Scope of access to revoke. Defaults to 'all' for full offboarding."
                },
                "emergency": {
                    "type": "boolean",
                    "description": (
                        "Set to true for security incidents requiring immediate revocation. "
                        "Elevates priority and triggers additional security actions."
                    )
                }
            },
            "required": ["username"]
        }
    },
    {
        "name": "get_user_status",
        "description": (
            "Look up an Active Directory user and return their current status. "
            "Returns account state (enabled/disabled), department, title, group memberships, "
            "last login time, M365 license, and mailbox status. "
            "Call this to verify a user exists before offboarding, or to check the result of an action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": (
                        "AD username (sAMAccountName) or full name to search. "
                        "Partial name matching is supported."
                    )
                }
            },
            "required": ["username"]
        }
    }
]


# =============================================================================
# MOCK DATA — simulates a realistic enterprise AD/Exchange/M365 environment
# _AD_USERS_DB is mutated by tool handlers so actions have persistent effects.
# =============================================================================

_DEPARTMENT_POLICIES = {
    "IT": {
        "standard_groups": [
            "IT-Staff", "VPN-Users", "Remote-Desktop-Users",
            "Server-Admins", "Helpdesk-Access", "Software-Deployment"
        ],
        "required_software": ["SolarWinds", "Microsoft SCCM", "PuTTY", "Wireshark"],
        "m365_license": "Microsoft365_E5",
        "data_access": "Elevated — Full IT infrastructure access",
        "mfa_required": True,
        "privileged_access": True,
        "compliance_notes": "ISO 27001 — privileged user monitoring required"
    },
    "Finance": {
        "standard_groups": [
            "Finance-Staff", "VPN-Users", "Accounting-Software-Users",
            "Finance-Reports-ReadOnly", "AP-AR-Access"
        ],
        "required_software": ["QuickBooks Enterprise", "Microsoft Office 365", "DocuSign"],
        "m365_license": "Microsoft365_E3",
        "data_access": "Restricted — Financial data only",
        "mfa_required": True,
        "privileged_access": False,
        "compliance_notes": "SOX compliance — audit logging enabled"
    },
    "HR": {
        "standard_groups": [
            "HR-Staff", "VPN-Users", "HRIS-System-Access",
            "Employee-Records-Access", "Payroll-View"
        ],
        "required_software": ["Workday", "DocuSign", "Microsoft Office 365"],
        "m365_license": "Microsoft365_E3",
        "data_access": "Restricted — PII and employee data",
        "mfa_required": True,
        "privileged_access": False,
        "compliance_notes": "GDPR/CCPA — PII handling training required"
    },
    "Engineering": {
        "standard_groups": [
            "Engineering-Staff", "VPN-Users", "GitHub-Enterprise",
            "Dev-Servers-Access", "CI-CD-Pipeline", "NPM-Registry"
        ],
        "required_software": ["JetBrains Suite", "Docker Desktop", "Git", "VS Code"],
        "m365_license": "Microsoft365_E3",
        "data_access": "Standard — Code repositories and dev environments",
        "mfa_required": True,
        "privileged_access": False,
        "compliance_notes": "IP protection — code signing required for production deployments"
    },
    "Sales": {
        "standard_groups": [
            "Sales-Staff", "VPN-Users", "CRM-Users",
            "Sales-Reports", "Partner-Portal-Access"
        ],
        "required_software": ["Salesforce", "ZoomInfo", "Microsoft Office 365", "Zoom"],
        "m365_license": "Microsoft365_Business_Premium",
        "data_access": "Standard — CRM and customer data",
        "mfa_required": True,
        "privileged_access": False,
        "compliance_notes": "GDPR — customer data handling policy applies"
    }
}

_ROLE_TEMPLATES = {
    "system administrator": {
        "phases": {
            "pre_day_one": [
                "Create AD account in CORP domain",
                "Assign IT-Staff, Server-Admins, VPN-Users, Remote-Desktop-Users groups",
                "Provision Exchange mailbox (UserMailbox)",
                "Assign Microsoft365_E5 license",
                "Request Privileged Access Workstation (PAW) from asset management",
                "Generate temporary credentials for monitoring systems (SolarWinds)"
            ],
            "day_one": [
                "Complete security awareness training — privileged accounts module",
                "Set up MFA using FIDO2 hardware key (required for IT-Staff)",
                "Configure Privileged Access Workstation",
                "Review IT runbooks and escalation procedures"
            ],
            "week_one": [
                "Complete Active Directory administration training",
                "Shadow senior sysadmin for environment orientation",
                "Document emergency contact and on-call rotation schedule",
                "Submit vendor portal access requests (SCCM, SolarWinds)"
            ]
        },
        "requires_background_check": True,
        "security_clearance": "High"
    },
    "software engineer": {
        "phases": {
            "pre_day_one": [
                "Create AD account in CORP domain",
                "Assign Engineering-Staff, GitHub-Enterprise, VPN-Users, Dev-Servers-Access groups",
                "Provision Exchange mailbox",
                "Assign Microsoft365_E3 license",
                "Create Jira and Confluence accounts",
                "Request dev environment provisioning (VM or cloud workspace)"
            ],
            "day_one": [
                "Complete security awareness training",
                "Set up MFA using authenticator app",
                "Configure development workstation and verify dev environment",
                "Clone starter repositories and run smoke tests"
            ],
            "week_one": [
                "Complete code review process and branching strategy training",
                "Introduction to CI/CD pipeline",
                "Meet with tech lead for project-specific onboarding",
                "Complete GDPR and data handling training"
            ]
        },
        "requires_background_check": False,
        "security_clearance": "Standard"
    },
    "finance manager": {
        "phases": {
            "pre_day_one": [
                "Create AD account in CORP domain",
                "Assign Finance-Staff, AP-AR-Access, VPN-Users groups",
                "Provision Exchange mailbox",
                "Assign Microsoft365_E3 license",
                "Request accounting system access (requires CFO approval)",
                "Schedule SOX compliance training"
            ],
            "day_one": [
                "Complete SOX compliance and security training",
                "Set up MFA",
                "Introduction to financial reporting systems",
                "Review data classification and confidentiality policy"
            ],
            "week_one": [
                "Complete audit trail and logging training",
                "Review quarter-close procedures with controller",
                "Meet with CFO for scope of responsibilities",
                "Complete expense reporting system orientation"
            ]
        },
        "requires_background_check": True,
        "security_clearance": "High"
    },
    "hr coordinator": {
        "phases": {
            "pre_day_one": [
                "Create AD account in CORP domain",
                "Assign HR-Staff, HRIS-System-Access, VPN-Users, Employee-Records-Access groups",
                "Provision Exchange mailbox",
                "Assign Microsoft365_E3 license",
                "Schedule GDPR and PII handling training"
            ],
            "day_one": [
                "Complete GDPR/CCPA and privacy training",
                "Set up MFA",
                "Introduction to Workday HRIS",
                "Review employee data handling policies"
            ],
            "week_one": [
                "Complete benefits administration system training",
                "Shadow senior HR team member",
                "Review onboarding and offboarding procedures",
                "Complete I-9 verification process training"
            ]
        },
        "requires_background_check": True,
        "security_clearance": "High"
    }
}

# In-memory AD user store — mutable so tool effects are visible across calls
_AD_USERS_DB: dict[str, dict] = {
    "jsmith": {
        "status": "enabled",
        "full_name": "John Smith",
        "department": "Engineering",
        "title": "Software Engineer",
        "email": "jsmith@contoso.com",
        "groups": ["Engineering-Staff", "VPN-Users", "GitHub-Enterprise", "All-Staff", "Domain-Users"],
        "last_login": "2025-06-08T09:15:33",
        "m365_license": "Microsoft365_E3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 2340,
        "ou": "OU=Engineering,OU=Departments,DC=contoso,DC=local",
        "created": "2023-03-15"
    },
    "mwilliams": {
        "status": "enabled",
        "full_name": "Maria Williams",
        "department": "Finance",
        "title": "Finance Manager",
        "email": "mwilliams@contoso.com",
        "groups": ["Finance-Staff", "VPN-Users", "AP-AR-Access", "Finance-Reports-ReadOnly", "All-Staff", "Domain-Users"],
        "last_login": "2025-06-09T08:02:11",
        "m365_license": "Microsoft365_E3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 1890,
        "ou": "OU=Finance,OU=Departments,DC=contoso,DC=local",
        "created": "2021-09-01"
    },
    "rjohnson": {
        "status": "enabled",
        "full_name": "Robert Johnson",
        "department": "IT",
        "title": "System Administrator",
        "email": "rjohnson@contoso.com",
        "groups": ["IT-Staff", "Server-Admins", "VPN-Users", "Remote-Desktop-Users", "All-Staff", "Domain-Users"],
        "last_login": "2025-06-09T07:44:02",
        "m365_license": "Microsoft365_E5",
        "mailbox_enabled": True,
        "mailbox_size_mb": 4120,
        "ou": "OU=IT,OU=Departments,DC=contoso,DC=local",
        "created": "2020-06-01"
    }
}

_LICENSE_INVENTORY = {
    "Microsoft365_E3": {"available": 47, "total": 100},
    "Microsoft365_E5": {"available": 12, "total": 25},
    "Microsoft365_F3": {"available": 23, "total": 30},
    "Microsoft365_Business_Premium": {"available": 8, "total": 15}
}

_LICENSE_SERVICES = {
    "Microsoft365_E3": [
        "Exchange Online P1", "SharePoint Online P2", "Microsoft Teams",
        "Intune Device Management", "Office Apps (Desktop + Mobile)"
    ],
    "Microsoft365_E5": [
        "Exchange Online P2", "SharePoint Online P2", "Microsoft Teams",
        "Intune Device Management", "Office Apps (Desktop + Mobile)",
        "Microsoft Defender for Endpoint P2", "Azure AD Premium P2",
        "Microsoft Purview (Compliance)", "Power BI Pro"
    ],
    "Microsoft365_F3": [
        "Exchange Online K1", "SharePoint Online F1",
        "Microsoft Teams Essentials", "Office Mobile Apps Only"
    ],
    "Microsoft365_Business_Premium": [
        "Exchange Online P1", "SharePoint Online P1", "Microsoft Teams",
        "Intune Device Management", "Office Apps (Desktop + Mobile)",
        "Microsoft Defender for Business"
    ]
}


# =============================================================================
# TOOL HANDLERS
# Each function is the implementation behind one MCP tool.
# =============================================================================

def handle_get_onboarding_template(role: str) -> dict:
    role_key = role.lower().strip()

    # Exact match, then keyword match
    template = _ROLE_TEMPLATES.get(role_key)
    if not template:
        for key, tmpl in _ROLE_TEMPLATES.items():
            if any(word in role_key for word in key.split()):
                template = tmpl
                role_key = key
                break

    if not template:
        template = {
            "phases": {
                "pre_day_one": [
                    "Create AD account in CORP domain",
                    "Assign department-standard groups — use get_department_policies to determine correct groups",
                    "Provision Exchange mailbox (UserMailbox)",
                    "Assign appropriate M365 license based on department policy"
                ],
                "day_one": [
                    "Complete security awareness training",
                    "Set up MFA",
                    "Configure workstation"
                ],
                "week_one": [
                    "Role-specific onboarding sessions with manager",
                    "Review relevant policies and procedures"
                ]
            },
            "requires_background_check": False,
            "security_clearance": "Standard",
            "note": f"No specific template found for '{role}'. Generic template returned. Consult HR/manager for role-specific requirements."
        }

    return {
        "role": role,
        "template_matched": "note" not in template,
        "template": template,
        "retrieved_at": datetime.now().isoformat(),
        "source": "HR-IT Onboarding Policy v4.2"
    }


def handle_get_department_policies(department: str) -> dict:
    dept_key = department.strip().title()
    policy = _DEPARTMENT_POLICIES.get(dept_key)

    if not policy:
        for key in _DEPARTMENT_POLICIES:
            if department.lower() in key.lower():
                policy = _DEPARTMENT_POLICIES[key]
                dept_key = key
                break

    if not policy:
        return {
            "department": department,
            "found": False,
            "error": f"No policy configuration found for department '{department}'. Check spelling or contact IT Policy.",
            "available_departments": list(_DEPARTMENT_POLICIES.keys())
        }

    return {
        "department": dept_key,
        "found": True,
        "policies": policy,
        "retrieved_at": datetime.now().isoformat(),
        "source": "IT Security Policy Framework v2.1"
    }


def handle_create_ad_user(
    first_name: str,
    last_name: str,
    department: str,
    job_title: str,
    manager: str = None,
    start_date: str = None,
    location: str = "Main Office"
) -> dict:
    base_username = (first_name[0] + last_name).lower().replace(" ", "").replace("-", "")
    username = base_username

    # Ensure uniqueness
    counter = 2
    while username in _AD_USERS_DB:
        username = f"{base_username}{counter}"
        counter += 1

    upn = f"{username}@contoso.com"
    temp_password = f"Welcome1!{random.randint(100, 999)}"

    ou_map = {
        "IT": "OU=IT,OU=Departments,DC=contoso,DC=local",
        "Finance": "OU=Finance,OU=Departments,DC=contoso,DC=local",
        "HR": "OU=HR,OU=Departments,DC=contoso,DC=local",
        "Engineering": "OU=Engineering,OU=Departments,DC=contoso,DC=local",
        "Sales": "OU=Sales,OU=Departments,DC=contoso,DC=local"
    }
    ou = ou_map.get(department.title(), "OU=General,OU=Departments,DC=contoso,DC=local")

    _AD_USERS_DB[username] = {
        "status": "enabled",
        "full_name": f"{first_name} {last_name}",
        "department": department,
        "title": job_title,
        "email": upn,
        "groups": ["All-Staff", "Domain-Users"],
        "last_login": None,
        "m365_license": None,
        "mailbox_enabled": False,
        "mailbox_size_mb": 0,
        "ou": ou,
        "created": datetime.now().isoformat(),
        "manager": manager
    }

    return {
        "success": True,
        "action": "AD_USER_CREATED",
        "username": username,
        "upn": upn,
        "display_name": f"{first_name} {last_name}",
        "department": department,
        "job_title": job_title,
        "ou_path": ou,
        "domain": "CONTOSO",
        "manager": manager or "Not specified",
        "start_date": start_date or "Not specified",
        "location": location,
        "temporary_password": temp_password,
        "password_change_required": True,
        "account_enabled": True,
        "created_at": datetime.now().isoformat(),
        "note": "Account created. Password must be changed on first login. MFA enrollment required within 24 hours."
    }


def handle_assign_ad_groups(username: str, groups: list) -> dict:
    if username not in _AD_USERS_DB:
        return {
            "success": False,
            "error": f"User '{username}' not found in Active Directory. Verify the username with get_user_status."
        }

    assigned = []
    failed = []

    for group in groups:
        if "INVALID" in group.upper() or "NOTEXIST" in group.upper():
            failed.append({"group": group, "error": "Group not found in Active Directory"})
        else:
            if group not in _AD_USERS_DB[username]["groups"]:
                _AD_USERS_DB[username]["groups"].append(group)
            assigned.append({
                "group": group,
                "status": "assigned",
                "type": "Security"
            })

    return {
        "success": len(failed) == 0,
        "partial_success": len(assigned) > 0 and len(failed) > 0,
        "action": "AD_GROUPS_ASSIGNED",
        "username": username,
        "groups_assigned": assigned,
        "groups_failed": failed,
        "total_assigned": len(assigned),
        "current_group_memberships": _AD_USERS_DB[username]["groups"],
        "completed_at": datetime.now().isoformat()
    }


def handle_provision_exchange_mailbox(username: str, mailbox_type: str = "UserMailbox") -> dict:
    if username not in _AD_USERS_DB:
        return {
            "success": False,
            "error": f"User '{username}' not found in Active Directory. Cannot provision mailbox."
        }

    if _AD_USERS_DB[username]["mailbox_enabled"]:
        return {
            "success": False,
            "already_exists": True,
            "username": username,
            "email": _AD_USERS_DB[username]["email"],
            "message": "Mailbox already provisioned for this user."
        }

    _AD_USERS_DB[username]["mailbox_enabled"] = True
    email = _AD_USERS_DB[username]["email"]

    return {
        "success": True,
        "action": "EXCHANGE_MAILBOX_PROVISIONED",
        "username": username,
        "email_address": email,
        "mailbox_type": mailbox_type,
        "exchange_server": "EXCH-HYB-01.contoso.local",
        "routing_mode": "Hybrid (On-prem → Exchange Online)",
        "database": "MailboxDB-03",
        "quota_mb": 51200,
        "archive_enabled": False,
        "smtp_aliases": [email, f"{username}@contoso.onmicrosoft.com"],
        "provisioned_at": datetime.now().isoformat(),
        "aad_connect_sync_eta": "~30 minutes",
        "note": "Mailbox enabled. Email routing active after next AAD Connect sync cycle (~30 min)."
    }


def handle_assign_m365_license(username: str, license_type: str) -> dict:
    if username not in _AD_USERS_DB:
        return {
            "success": False,
            "error": f"User '{username}' not found in Active Directory."
        }

    if not _AD_USERS_DB[username]["mailbox_enabled"]:
        return {
            "success": False,
            "error": "Exchange mailbox must be provisioned before assigning an M365 license.",
            "recommendation": "Call provision_exchange_mailbox first, then retry this step."
        }

    if _AD_USERS_DB[username].get("m365_license"):
        return {
            "success": False,
            "already_assigned": True,
            "username": username,
            "current_license": _AD_USERS_DB[username]["m365_license"],
            "message": f"License already assigned. Use license management portal to change or upgrade."
        }

    inventory = _LICENSE_INVENTORY.get(license_type, {})
    available = inventory.get("available", 0)
    if available == 0:
        return {
            "success": False,
            "error": f"No available licenses for {license_type}. Contact IT Procurement to purchase more.",
            "licenses_available": 0,
            "licenses_total": inventory.get("total", 0)
        }

    _AD_USERS_DB[username]["m365_license"] = license_type
    _LICENSE_INVENTORY[license_type]["available"] -= 1

    return {
        "success": True,
        "action": "M365_LICENSE_ASSIGNED",
        "username": username,
        "license_assigned": license_type,
        "services_enabled": _LICENSE_SERVICES.get(license_type, []),
        "licenses_remaining": _LICENSE_INVENTORY[license_type]["available"],
        "tenant": "contoso.onmicrosoft.com",
        "activation_eta": "~15 minutes",
        "assigned_at": datetime.now().isoformat(),
        "note": "License assigned. Services will activate within 15–30 minutes."
    }


def handle_disable_ad_user(username: str, reason: str, move_to_disabled_ou: bool = True) -> dict:
    # Support lookup by username or partial full name
    found_username = _find_user(username)
    if not found_username:
        return {
            "success": False,
            "error": f"User '{username}' not found in Active Directory.",
            "suggestion": "Use get_user_status to find the correct username."
        }

    if _AD_USERS_DB[found_username]["status"] == "disabled":
        return {
            "success": False,
            "already_disabled": True,
            "username": found_username,
            "message": f"Account '{found_username}' is already disabled.",
            "disabled_since": _AD_USERS_DB[found_username].get("disabled_at", "Unknown")
        }

    previous_ou = _AD_USERS_DB[found_username]["ou"]
    _AD_USERS_DB[found_username]["status"] = "disabled"
    _AD_USERS_DB[found_username]["disabled_at"] = datetime.now().isoformat()
    _AD_USERS_DB[found_username]["disabled_reason"] = reason

    if move_to_disabled_ou:
        _AD_USERS_DB[found_username]["ou"] = "OU=DisabledUsers,DC=contoso,DC=local"

    return {
        "success": True,
        "action": "AD_USER_DISABLED",
        "username": found_username,
        "full_name": _AD_USERS_DB[found_username]["full_name"],
        "previous_status": "enabled",
        "new_status": "disabled",
        "reason": reason,
        "moved_to_disabled_ou": move_to_disabled_ou,
        "previous_ou": previous_ou,
        "new_ou": _AD_USERS_DB[found_username]["ou"],
        "all_sessions_terminated": True,
        "logon_blocked": True,
        "disabled_at": _AD_USERS_DB[found_username]["disabled_at"],
        "performed_by": "IT-Automation-Agent",
        "note": "Account disabled. All active sessions terminated. User cannot log in."
    }


def handle_revoke_access(username: str, scope: str = "all", emergency: bool = False) -> dict:
    found_username = _find_user(username)
    if not found_username:
        return {
            "success": False,
            "error": f"User '{username}' not found in Active Directory."
        }

    user = _AD_USERS_DB[found_username]
    removed_groups = [g for g in user["groups"] if g != "Domain-Users"]
    actions_taken = []

    if scope in ("all", "groups_only"):
        _AD_USERS_DB[found_username]["groups"] = ["Domain-Users"]
        actions_taken.append({
            "action": "AD_GROUPS_REMOVED",
            "detail": f"Removed from {len(removed_groups)} security groups",
            "groups_removed": removed_groups
        })

    if scope in ("all", "m365_only"):
        prev_license = _AD_USERS_DB[found_username].get("m365_license")
        _AD_USERS_DB[found_username]["m365_license"] = None
        if prev_license and prev_license in _LICENSE_INVENTORY:
            _LICENSE_INVENTORY[prev_license]["available"] += 1
        actions_taken.append({
            "action": "M365_LICENSE_REVOKED",
            "detail": f"License {prev_license or 'none'} removed; all Azure AD/M365 sessions terminated"
        })

    if scope in ("all", "vpn_only"):
        actions_taken.append({
            "action": "VPN_CERTIFICATE_REVOKED",
            "detail": "GlobalProtect VPN certificate revoked; active VPN sessions dropped"
        })

    if scope == "all":
        actions_taken.extend([
            {
                "action": "EMAIL_DELEGATION_REMOVED",
                "detail": "All mailbox Send-As and Full Access delegations removed"
            },
            {
                "action": "EMAIL_FORWARDING_BLOCKED",
                "detail": "Auto-forward rules and external forwarding rules disabled"
            },
            {
                "action": "MFA_TOKENS_INVALIDATED",
                "detail": "All registered MFA devices and authenticator tokens revoked"
            },
            {
                "action": "CONDITIONAL_ACCESS_BLOCKED",
                "detail": "Azure AD Conditional Access policy 'Block-Offboarded-Users' applied"
            }
        ])

        if emergency:
            actions_taken.append({
                "action": "INCIDENT_RESPONSE_TRIGGERED",
                "detail": "Security team notified; account flagged for forensic review; sign-in logs exported"
            })

    audit_ticket = f"INC-{random.randint(10000, 99999)}"

    return {
        "success": True,
        "action": "ACCESS_REVOKED",
        "username": found_username,
        "full_name": user["full_name"],
        "scope": scope,
        "emergency_mode": emergency,
        "priority": "IMMEDIATE" if emergency else "STANDARD",
        "actions_taken": actions_taken,
        "total_actions": len(actions_taken),
        "audit_ticket": audit_ticket,
        "completed_at": datetime.now().isoformat(),
        "note": f"Access revocation complete. Audit ticket {audit_ticket} created for compliance records."
    }


def handle_get_user_status(username: str) -> dict:
    found_username = _find_user(username)

    if not found_username:
        return {
            "found": False,
            "searched": username,
            "error": "User not found in Active Directory.",
            "suggestion": "Verify the username (sAMAccountName) or try a partial full name search."
        }

    user = _AD_USERS_DB[found_username]
    return {
        "found": True,
        "username": found_username,
        "full_name": user.get("full_name"),
        "status": user["status"],
        "department": user.get("department"),
        "title": user.get("title"),
        "email": user.get("email"),
        "ou_path": user.get("ou"),
        "manager": user.get("manager"),
        "groups": user.get("groups", []),
        "group_count": len(user.get("groups", [])),
        "last_login": user.get("last_login"),
        "m365_license": user.get("m365_license"),
        "mailbox_enabled": user.get("mailbox_enabled", False),
        "mailbox_size_mb": user.get("mailbox_size_mb") if user.get("mailbox_enabled") else None,
        "created": user.get("created"),
        "disabled_at": user.get("disabled_at"),
        "disabled_reason": user.get("disabled_reason"),
        "retrieved_at": datetime.now().isoformat()
    }


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _find_user(query: str) -> str | None:
    """Return the sAMAccountName for a query (exact username or partial full name)."""
    if query in _AD_USERS_DB:
        return query
    query_lower = query.lower()
    for uname, data in _AD_USERS_DB.items():
        if query_lower in data.get("full_name", "").lower():
            return uname
    return None


# =============================================================================
# TOOL DISPATCHER
# Maps tool names → handler functions and executes them, returning JSON strings.
# =============================================================================

_TOOL_HANDLERS = {
    "get_onboarding_template": handle_get_onboarding_template,
    "get_department_policies": handle_get_department_policies,
    "create_ad_user": handle_create_ad_user,
    "assign_ad_groups": handle_assign_ad_groups,
    "provision_exchange_mailbox": handle_provision_exchange_mailbox,
    "assign_m365_license": handle_assign_m365_license,
    "disable_ad_user": handle_disable_ad_user,
    "revoke_access": handle_revoke_access,
    "get_user_status": handle_get_user_status
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Dispatch a model-requested tool call to the appropriate handler.
    Always returns a JSON string — errors are JSON too, so the model can reason about them.
    """
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({
            "error": f"Unknown tool: '{tool_name}'",
            "available_tools": list(_TOOL_HANDLERS.keys())
        })

    try:
        result = handler(**tool_input)
        return json.dumps(result, indent=2, default=str)
    except TypeError as e:
        return json.dumps({
            "error": f"Invalid parameters for tool '{tool_name}': {e}",
            "received_input": tool_input
        })
    except Exception as e:
        return json.dumps({
            "error": f"Tool execution error in '{tool_name}': {e}",
            "tool": tool_name
        })
