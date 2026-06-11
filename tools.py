"""
tools.py — MCP-style tool definitions and mocked handlers.

Each entry in TOOL_DEFINITIONS is passed directly to the Anthropic API `tools=`
parameter. The LLM reads these descriptions to decide which tools to call.

Handler functions simulate the MOCKCO hybrid enterprise environment:
  - Domain: MOCKCO (mockcompany.local / mockcompany.com)
  - Location-based OU structure (Holland, Grand Rapids, Kalamazoo, Big Rapids)
  - Hybrid Exchange (on-prem + Exchange Online)
  - M365 license tiers by role: E5 (executives/IT), E3 (office/engineering),
    F3 (frontline), Business Premium (purchasing/prod control)
  - Separate admin accounts (jdoe / jdoe-admin)
  - Email format: firstname.lastname@mockcompany.com
  - Username format: firstinitiallastname (jdoe)

In-memory state (_AD_USERS_DB) persists within a session so tool effects
are visible across calls (e.g. create then verify, or offboard then check status).
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
            "Retrieve the standard onboarding checklist and required steps for a given job role "
            "at MOCKCO. Call this first when processing any new hire request to understand what "
            "steps are required. Returns a structured template with phases (pre_day_one, day_one, "
            "week_one), required group memberships, license tier, and any special requirements "
            "such as admin account provisioning or background check flags."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": (
                        "The job role or title of the new employee. "
                        "Examples: 'Process Engineer', 'HR Generalist', 'IT Admin', "
                        "'Truck Driver', 'Furnace Operator', 'General Manager', 'Purchasing Agent'"
                    )
                }
            },
            "required": ["role"]
        }
    },
    {
        "name": "get_department_policies",
        "description": (
            "Retrieve MOCKCO IT policies, required AD security group memberships, "
            "distribution list assignments, software requirements, and compliance rules "
            "for a specific department. Call this to determine which AD groups, license tier, "
            "and software stack are standard for a department before provisioning accounts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": (
                        "The department name at MOCKCO. "
                        "Valid departments: IT, HR, Engineering, Quality, Maintenance, "
                        "Production, Operations, Supply Chain, Logistics, Sales"
                    )
                }
            },
            "required": ["department"]
        }
    },
    {
        "name": "create_ad_user",
        "description": (
            "Create a new Active Directory user account in the MOCKCO domain (mockcompany.local). "
            "Username format is firstinitiallastname (e.g. jdoe). "
            "Email format is firstname.lastname@mockcompany.com. "
            "OU placement is based on the employee's primary work location "
            "(Holland, Grand Rapids, Kalamazoo, or Big Rapids). "
            "Call this after gathering all required user information. "
            "Returns the generated username (sAMAccountName), UPN, OU path, email address, "
            "and temporary password. For privileged IT roles, a separate admin account "
            "(username-admin) is also created automatically."
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
                "location": {
                    "type": "string",
                    "description": (
                        "Primary work location. Must be one of: "
                        "Holland, Grand Rapids, Kalamazoo, Big Rapids, Remote. "
                        "Remote users are placed under Grand Rapids OU."
                    )
                },
                "manager": {
                    "type": "string",
                    "description": "Manager's username or full name (optional)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Employment start date in YYYY-MM-DD format (optional)"
                },
                "is_contractor": {
                    "type": "boolean",
                    "description": "Set to true for contractors. Affects license tier and group assignments."
                }
            },
            "required": ["first_name", "last_name", "department", "job_title", "location"]
        }
    },
    {
        "name": "assign_ad_groups",
        "description": (
            "Add a user to one or more Active Directory security groups or distribution lists "
            "in the MOCKCO domain. "
            "Security groups follow the naming convention SG-Department-Access or SG-Role-Title. "
            "Distribution lists follow DL-GroupName convention. "
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
                    "description": (
                        "List of AD security group or distribution list names to add the user to. "
                        "Examples: SG-Engineering-Standard, SG-Role-Engineer, DL-Engineering, DL-AllEmployees"
                    )
                }
            },
            "required": ["username", "groups"]
        }
    },
    {
        "name": "provision_exchange_mailbox",
        "description": (
            "Enable an Exchange mailbox for a user in the MOCKCO hybrid Exchange environment "
            "(on-prem Exchange + Exchange Online via AAD Connect). "
            "Email address will be firstname.lastname@mockcompany.com. "
            "Must be called before assigning M365 licenses. "
            "Supports UserMailbox, SharedMailbox (SM- prefix), and RoomMailbox (RM- prefix). "
            "Returns mailbox details, SMTP addresses, and expected AAD Connect sync time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "The AD username (sAMAccountName) to enable a mailbox for"
                },
                "mailbox_type": {
                    "type": "string",
                    "enum": ["UserMailbox", "SharedMailbox", "RoomMailbox"],
                    "description": (
                        "Type of mailbox. UserMailbox for standard employees. "
                        "SharedMailbox for shared inboxes (e.g. SM-HR, SM-Shipping). "
                        "RoomMailbox for conference rooms (e.g. RM-GR-ConfRoom1)."
                    )
                }
            },
            "required": ["username"]
        }
    },
    {
        "name": "assign_m365_license",
        "description": (
            "Assign a Microsoft 365 license to a MOCKCO user, enabling cloud services. "
            "Requires Exchange mailbox to already be provisioned. "
            "MOCKCO license tiers: "
            "E5 = Executives, General Managers, IT Admins, Data Analysts (security + compliance features). "
            "E3 = Engineers, Quality, HR, Sales Managers, office staff. "
            "F3 = Frontline/production workers, drivers, operators, technicians. "
            "Business_Premium = Purchasing, Production Control. "
            "Contractors typically receive F3 or no license. "
            "Returns license type assigned, services enabled, and remaining license inventory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "The AD username (sAMAccountName) to assign a license to"
                },
                "license_type": {
                    "type": "string",
                    "enum": [
                        "Microsoft365_E5",
                        "Microsoft365_E3",
                        "Microsoft365_F3",
                        "Microsoft365_Business_Premium"
                    ],
                    "description": (
                        "M365 license SKU appropriate for the role. "
                        "E5: executives, IT admins, general managers, data analysts. "
                        "E3: engineers, quality, HR generalists, sales managers. "
                        "F3: production workers, drivers, operators, frontline staff. "
                        "Business_Premium: purchasing agents, production control managers."
                    )
                }
            },
            "required": ["username", "license_type"]
        }
    },
    {
        "name": "disable_ad_user",
        "description": (
            "Disable an Active Directory user account in the MOCKCO domain, immediately "
            "preventing login and terminating all active sessions. "
            "Moves account to the top-level Disabled Users OU. "
            "Resets the account password as part of the disable process. "
            "This is the primary action for both standard and emergency offboarding. "
            "Returns confirmation, timestamp, previous OU, and new OU location."
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
                        "Reason for disabling. "
                        "Examples: 'Voluntary resignation', 'Contract end', "
                        "'Termination for cause', 'Security incident'"
                    )
                },
                "move_to_disabled_ou": {
                    "type": "boolean",
                    "description": "Move account to Disabled Users OU. Defaults to true."
                }
            },
            "required": ["username", "reason"]
        }
    },
    {
        "name": "revoke_access",
        "description": (
            "Revoke access for a departing MOCKCO employee. "
            "Removes from all AD security groups and distribution lists, "
            "invalidates M365/Azure AD sessions, blocks sign-in in Azure AD, "
            "removes email delegations, and handles mailbox disposition. "
            "For resignations: can optionally enable email forwarding to manager. "
            "For terminations: immediate revocation, no forwarding without explicit approval. "
            "For security incidents: set emergency=true to trigger incident response, "
            "security team notification, and forensic log export. "
            "OneDrive access is transferred to manager or HR. "
            "Returns all actions taken and an audit ticket number."
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
                    "description": "Scope of revocation. Defaults to 'all' for full offboarding."
                },
                "emergency": {
                    "type": "boolean",
                    "description": (
                        "Set true for security incidents. Triggers immediate elevated-priority "
                        "revocation, security team notification, and forensic log export."
                    )
                },
                "offboard_type": {
                    "type": "string",
                    "enum": ["resignation", "termination", "contract_end", "security_incident"],
                    "description": (
                        "Type of offboarding. Affects mailbox disposition and forwarding rules. "
                        "resignation: mailbox converted to shared, forwarding optional. "
                        "termination: immediate disable, no forwarding without approval. "
                        "security_incident: triggers emergency protocol."
                    )
                },
                "delegate_to": {
                    "type": "string",
                    "description": (
                        "Username of manager or HR contact to receive mailbox delegation "
                        "and OneDrive access transfer. Required for resignation offboarding."
                    )
                }
            },
            "required": ["username"]
        }
    },
    {
        "name": "get_user_status",
        "description": (
            "Look up an Active Directory user in the MOCKCO domain and return their current status. "
            "Returns account state (enabled/disabled), department, title, location, OU path, "
            "group memberships, last login, M365 license, mailbox status, and manager. "
            "Supports lookup by sAMAccountName (e.g. jdoe) or partial full name. "
            "Call this to verify a user exists before offboarding, or to audit account state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": (
                        "AD username (sAMAccountName) or full name to search. "
                        "Partial name matching supported. "
                        "Examples: 'jdoe', 'Jane Doe', 'Jane'"
                    )
                }
            },
            "required": ["username"]
        }
    }
]


# =============================================================================
# MOCK DATA — MOCKCO hybrid enterprise environment
#
# Domain:   MOCKCO (mockcompany.local)
# Email:    firstname.lastname@mockcompany.com
# Username: firstinitiallastname (jdoe)
# OUs:      Location-based (Holland, Grand Rapids, Kalamazoo, Big Rapids)
# =============================================================================

_DOMAIN = "mockcompany.local"
_EMAIL_DOMAIN = "mockcompany.com"
_NETBIOS = "MOCKCO"

# ---------------------------------------------------------------------------
# Location → OU path mapping
# Top-level OUs are by location, not department.
# Each location OU contains: Users, Computers, Servers, Groups
# ---------------------------------------------------------------------------
_LOCATION_OUS = {
    "Holland":      "OU=Users,OU=Holland,DC=mockcompany,DC=local",
    "Grand Rapids": "OU=Users,OU=GrandRapids,DC=mockcompany,DC=local",
    "Kalamazoo":    "OU=Users,OU=Kalamazoo,DC=mockcompany,DC=local",
    "Big Rapids":   "OU=Users,OU=BigRapids,DC=mockcompany,DC=local",
    "Remote":       "OU=Users,OU=GrandRapids,DC=mockcompany,DC=local",  # Remote → GR OU
}
_DISABLED_OU = "OU=Disabled Users,DC=mockcompany,DC=local"
_ADMIN_OU    = "OU=Admins,DC=mockcompany,DC=local"
_SVC_OU      = "OU=Service Accounts,DC=mockcompany,DC=local"

# ---------------------------------------------------------------------------
# Department policies
# Drives group assignments and license selection for each department.
# ---------------------------------------------------------------------------
_DEPARTMENT_POLICIES = {
    "IT": {
        "security_groups": [
            "SG-IT-Full",
            "SG-Role-ITAdmin",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-IT"],
        "required_software": [
            "SolarWinds Network Performance Monitor",
            "Microsoft RSAT (Remote Server Admin Tools)",
            "PuTTY / WinSCP",
            "Wireshark",
            "Veeam Backup Console",
            "Microsoft Endpoint Configuration Manager (SCCM)",
        ],
        "default_license": "Microsoft365_E5",
        "mfa_required": True,
        "admin_account_required": True,
        "privileged_access": True,
        "compliance_notes": "IT staff require separate admin accounts (username-admin). MFA enforced via Conditional Access.",
    },
    "HR": {
        "security_groups": [
            "SG-HR-Full",
            "SG-Role-HRGeneralist",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-HR"],
        "required_software": [
            "ADP Workforce Now",
            "Microsoft Office 365",
            "DocuSign",
            "Adobe Acrobat",
        ],
        "default_license": "Microsoft365_E3",
        "mfa_required": True,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "HR staff handle PII — data handling policy acknowledgment required on Day 1.",
    },
    "Engineering": {
        "security_groups": [
            "SG-Engineering-Standard",
            "SG-Role-Engineer",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Engineering"],
        "required_software": [
            "AutoCAD / SolidWorks",
            "Microsoft Office 365",
            "MATLAB (if applicable)",
            "ERP System Client (SAP / QAD)",
            "Adobe Acrobat",
        ],
        "default_license": "Microsoft365_E3",
        "mfa_required": True,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "Engineering drawings and IP are confidential — NDA acknowledgment required.",
    },
    "Quality": {
        "security_groups": [
            "SG-Quality-Read",
            "SG-Role-QualityEngineer",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Quality"],
        "required_software": [
            "Minitab",
            "Microsoft Office 365",
            "QMS Software (ISOTracker / ETQ)",
            "ERP System Client",
        ],
        "default_license": "Microsoft365_E3",
        "mfa_required": True,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "Quality staff have read access to production data. ISO 9001 training required.",
    },
    "Maintenance": {
        "security_groups": [
            "SG-Maintenance-Elevated",
            "SG-Role-MaintenanceTech",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Maintenance"],
        "required_software": [
            "CMMS (Maintenance Management System)",
            "Microsoft Office 365 (basic)",
        ],
        "default_license": "Microsoft365_F3",
        "mfa_required": False,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "Elevated access to maintenance systems and floor equipment networks.",
    },
    "Production": {
        "security_groups": [
            "SG-Production-Standard",
            "SG-Role-ProductionSupervisor",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Production"],
        "required_software": [
            "MES (Manufacturing Execution System)",
            "Microsoft Teams (mobile/kiosk)",
        ],
        "default_license": "Microsoft365_F3",
        "mfa_required": False,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "F3 license for frontline workers. Kiosk/shared workstation access only.",
    },
    "Operations": {
        "security_groups": [
            "SG-Operations-Managers",
            "SG-Role-GeneralManager",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Leadership"],
        "required_software": [
            "ERP System Client (SAP / QAD)",
            "Microsoft Office 365",
            "Power BI",
            "Microsoft Teams",
        ],
        "default_license": "Microsoft365_E5",
        "mfa_required": True,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "Operations managers have E5 for Power BI Pro and compliance features. MFA enforced.",
    },
    "Supply Chain": {
        "security_groups": [
            "SG-SupplyChain-Standard",
            "SG-Role-PurchasingAgent",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-SupplyChain"],
        "required_software": [
            "ERP System Client (SAP / QAD)",
            "Microsoft Office 365",
            "DocuSign",
            "Supplier Portal (web)",
        ],
        "default_license": "Microsoft365_Business_Premium",
        "mfa_required": True,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "Business Premium covers Intune device management for field procurement staff.",
    },
    "Logistics": {
        "security_groups": [
            "SG-Logistics-Standard",
            "SG-Role-Driver",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Logistics"],
        "required_software": [
            "TMS (Transportation Management System)",
            "Microsoft Teams (mobile)",
        ],
        "default_license": "Microsoft365_F3",
        "mfa_required": False,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "F3 for drivers and shipping clerks. Mobile-first access via Teams.",
    },
    "Sales": {
        "security_groups": [
            "SG-Sales-Standard",
            "SG-Role-SalesManager",
        ],
        "distribution_lists": ["DL-AllEmployees", "DL-Sales"],
        "required_software": [
            "Salesforce CRM",
            "Microsoft Office 365",
            "ZoomInfo",
            "Microsoft Teams",
            "DocuSign",
        ],
        "default_license": "Microsoft365_E3",
        "mfa_required": True,
        "admin_account_required": False,
        "privileged_access": False,
        "compliance_notes": "Sales staff have CRM access. Customer data handling policy applies.",
    },
}

# ---------------------------------------------------------------------------
# Role templates — phased onboarding checklists
# ---------------------------------------------------------------------------
_ROLE_TEMPLATES = {
    "it admin": {
        "phases": {
            "pre_day_one": [
                "Create standard AD account in MOCKCO domain (firstinitiallastname format)",
                "Create separate privileged admin account (username-admin) in OU=Admins",
                "Assign SG-IT-Full and SG-Role-ITAdmin to standard account",
                "Provision Exchange mailbox (UserMailbox) — email: firstname.lastname@mockcompany.com",
                "Assign Microsoft365_E5 license",
                "Request physical workstation (IT-issued, domain-joined)",
                "Provision VPN certificate (GlobalProtect)",
                "Add to SolarWinds and monitoring system access",
            ],
            "day_one": [
                "Security onboarding briefing — privileged account policy",
                "Enroll MFA — FIDO2 hardware key required for IT-Full accounts",
                "Configure admin workstation and verify domain trust",
                "Review IT runbooks, escalation matrix, and on-call rotation",
                "Verify admin account (username-admin) access to server OU",
            ],
            "week_one": [
                "Shadow senior sysadmin — environment walkthrough (all 4 locations)",
                "Review DR/BCP documentation and backup verification procedures",
                "Complete AD and Exchange hybrid training",
                "Submit access requests: Veeam, SCCM, SolarWinds, firewall consoles",
                "Review svc-* account inventory and service dependencies",
            ],
        },
        "requires_background_check": True,
        "admin_account_required": True,
        "security_clearance": "High",
        "license_tier": "Microsoft365_E5",
    },
    "process engineer": {
        "phases": {
            "pre_day_one": [
                "Create AD account in MOCKCO domain",
                "Assign SG-Engineering-Standard and SG-Role-Engineer",
                "Provision Exchange mailbox — email: firstname.lastname@mockcompany.com",
                "Assign Microsoft365_E3 license",
                "Request engineering workstation (CAD-capable hardware)",
                "Create ERP system account (QAD/SAP) — requires manager approval",
            ],
            "day_one": [
                "Security and NDA acknowledgment",
                "Enroll MFA via authenticator app",
                "Workstation setup — AutoCAD/SolidWorks license activation",
                "ERP system orientation with manager",
            ],
            "week_one": [
                "Engineering drawing control and document management training",
                "Introduction to plant layout and production process",
                "Meet with plant manager for scope of responsibilities",
                "Complete ISO 9001 awareness training",
            ],
        },
        "requires_background_check": False,
        "admin_account_required": False,
        "security_clearance": "Standard",
        "license_tier": "Microsoft365_E3",
    },
    "hr generalist": {
        "phases": {
            "pre_day_one": [
                "Create AD account in MOCKCO domain",
                "Assign SG-HR-Full and SG-Role-HRGeneralist",
                "Provision Exchange mailbox — email: firstname.lastname@mockcompany.com",
                "Add to DL-HR distribution list",
                "Assign Microsoft365_E3 license",
                "Request ADP Workforce Now access (requires HR Director approval)",
            ],
            "day_one": [
                "PII and data handling policy acknowledgment",
                "Enroll MFA via authenticator app",
                "ADP system orientation",
                "Review employee records access procedures",
            ],
            "week_one": [
                "Benefits administration system training",
                "Onboarding and offboarding procedure review",
                "I-9 verification process training",
                "FMLA and leave management orientation",
            ],
        },
        "requires_background_check": True,
        "admin_account_required": False,
        "security_clearance": "High",
        "license_tier": "Microsoft365_E3",
    },
    "general manager": {
        "phases": {
            "pre_day_one": [
                "Create AD account in MOCKCO domain",
                "Assign SG-Operations-Managers, SG-Role-GeneralManager, SG-Executives",
                "Provision Exchange mailbox — email: firstname.lastname@mockcompany.com",
                "Add to DL-Leadership distribution list",
                "Assign Microsoft365_E5 license",
                "Issue company laptop and mobile device",
                "Add to executive MFA Conditional Access policy",
            ],
            "day_one": [
                "Security briefing — executive account policy and phishing awareness",
                "Enroll MFA — hardware key or authenticator required",
                "ERP system and Power BI access setup",
                "Introduction to direct reports and plant leadership team",
            ],
            "week_one": [
                "Full plant walkthrough with operations team",
                "Review P&L, KPI dashboards, and reporting structure",
                "Meet with corporate team for strategic alignment",
                "Review safety and compliance obligations",
            ],
        },
        "requires_background_check": True,
        "admin_account_required": False,
        "security_clearance": "High",
        "license_tier": "Microsoft365_E5",
    },
    "truck driver": {
        "phases": {
            "pre_day_one": [
                "Create AD account in MOCKCO domain",
                "Assign SG-Logistics-Standard and SG-Role-Driver",
                "Provision Exchange mailbox (optional — many drivers use shared kiosk)",
                "Assign Microsoft365_F3 license",
                "Issue mobile device or verify BYOD enrollment in Intune",
            ],
            "day_one": [
                "Safety orientation — DOT compliance and vehicle inspection procedure",
                "TMS (Transportation Management System) mobile app setup",
                "Teams mobile app configuration for dispatch communication",
                "Review route assignment and check-in procedures",
            ],
            "week_one": [
                "Supervised route with senior driver",
                "Hazmat documentation review (if applicable)",
                "Review delivery exception and incident reporting procedures",
            ],
        },
        "requires_background_check": True,
        "admin_account_required": False,
        "security_clearance": "Standard",
        "license_tier": "Microsoft365_F3",
    },
    "furnace operator": {
        "phases": {
            "pre_day_one": [
                "Create AD account in MOCKCO domain (kiosk/shared workstation access)",
                "Assign SG-Production-Standard",
                "Assign Microsoft365_F3 license (Teams mobile for shift communication)",
                "Coordinate with Maintenance for equipment access card",
            ],
            "day_one": [
                "Safety orientation — PPE requirements, hot work procedures, lockout/tagout",
                "MES (Manufacturing Execution System) login and job entry training",
                "Emergency evacuation and spill response review",
            ],
            "week_one": [
                "Supervised operation with senior operator",
                "Process parameter and quality checkpoint training",
                "Review shift handover and log documentation procedures",
            ],
        },
        "requires_background_check": False,
        "admin_account_required": False,
        "security_clearance": "Standard",
        "license_tier": "Microsoft365_F3",
    },
    "purchasing agent": {
        "phases": {
            "pre_day_one": [
                "Create AD account in MOCKCO domain",
                "Assign SG-SupplyChain-Standard and SG-Role-PurchasingAgent",
                "Provision Exchange mailbox — email: firstname.lastname@mockcompany.com",
                "Assign Microsoft365_Business_Premium license",
                "Request ERP purchasing module access (requires Supply Chain Director approval)",
                "Add to supplier portal vendor list",
            ],
            "day_one": [
                "ERP purchasing module orientation",
                "Vendor management policy and procurement authority levels review",
                "DocuSign setup for PO approvals",
            ],
            "week_one": [
                "Supplier onboarding process training",
                "Spend category and preferred vendor list review",
                "Meet with Supply Chain Director for active projects",
            ],
        },
        "requires_background_check": False,
        "admin_account_required": False,
        "security_clearance": "Standard",
        "license_tier": "Microsoft365_Business_Premium",
    },
}

# ---------------------------------------------------------------------------
# In-memory AD user store — realistic MOCKCO seed users across locations
# Mutable so tool effects (create, disable, revoke) persist within a session
# ---------------------------------------------------------------------------
_AD_USERS_DB: dict[str, dict] = {
    # Grand Rapids — IT (admin + standard pair)
    "adevries": {
        "status": "enabled",
        "full_name": "Andrew DeVries",
        "department": "IT",
        "title": "System Administrator",
        "email": "andrew.devries@mockcompany.com",
        "groups": [
            "SG-IT-Full", "SG-Role-ITAdmin",
            "DL-AllEmployees", "DL-IT",
            "SG-Remote-Users",
        ],
        "last_login": "2026-06-09T07:30:00",
        "m365_license": "Microsoft365_E5",
        "mailbox_enabled": True,
        "mailbox_size_mb": 8420,
        "ou": "OU=Users,OU=GrandRapids,DC=mockcompany,DC=local",
        "location": "Grand Rapids",
        "manager": "cthompson",
        "created": "2021-03-01",
        "is_contractor": False,
    },
    "adevries-admin": {
        "status": "enabled",
        "full_name": "Andrew DeVries (Admin)",
        "department": "IT",
        "title": "System Administrator — Privileged Account",
        "email": None,
        "groups": ["SG-IT-Full", "SG-Role-ITAdmin", "Domain Admins"],
        "last_login": "2026-06-09T08:15:00",
        "m365_license": None,
        "mailbox_enabled": False,
        "mailbox_size_mb": 0,
        "ou": "OU=Admins,DC=mockcompany,DC=local",
        "location": "Grand Rapids",
        "manager": "adevries",
        "created": "2021-03-01",
        "is_contractor": False,
        "admin_account": True,
    },
    # Grand Rapids — Operations (General Manager)
    "cthompson": {
        "status": "enabled",
        "full_name": "Carol Thompson",
        "department": "Operations",
        "title": "General Manager",
        "email": "carol.thompson@mockcompany.com",
        "groups": [
            "SG-Operations-Managers", "SG-Role-GeneralManager", "SG-Executives",
            "DL-AllEmployees", "DL-Leadership",
        ],
        "last_login": "2026-06-09T08:00:00",
        "m365_license": "Microsoft365_E5",
        "mailbox_enabled": True,
        "mailbox_size_mb": 12100,
        "ou": "OU=Users,OU=GrandRapids,DC=mockcompany,DC=local",
        "location": "Grand Rapids",
        "manager": None,
        "created": "2019-08-15",
        "is_contractor": False,
    },
    # Holland — Engineering
    "bmartinez": {
        "status": "enabled",
        "full_name": "Brian Martinez",
        "department": "Engineering",
        "title": "Process Engineer",
        "email": "brian.martinez@mockcompany.com",
        "groups": [
            "SG-Engineering-Standard", "SG-Role-Engineer",
            "DL-AllEmployees", "DL-Engineering",
        ],
        "last_login": "2026-06-08T16:45:00",
        "m365_license": "Microsoft365_E3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 3210,
        "ou": "OU=Users,OU=Holland,DC=mockcompany,DC=local",
        "location": "Holland",
        "manager": "cthompson",
        "created": "2022-05-10",
        "is_contractor": False,
    },
    # Holland — HR
    "slopez": {
        "status": "enabled",
        "full_name": "Sandra Lopez",
        "department": "HR",
        "title": "HR Generalist",
        "email": "sandra.lopez@mockcompany.com",
        "groups": [
            "SG-HR-Full", "SG-Role-HRGeneralist",
            "DL-AllEmployees", "DL-HR",
        ],
        "last_login": "2026-06-09T09:10:00",
        "m365_license": "Microsoft365_E3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 2870,
        "ou": "OU=Users,OU=Holland,DC=mockcompany,DC=local",
        "location": "Holland",
        "manager": "cthompson",
        "created": "2020-11-30",
        "is_contractor": False,
    },
    # Kalamazoo — Production (frontline)
    "rwilson": {
        "status": "enabled",
        "full_name": "Robert Wilson",
        "department": "Production",
        "title": "Furnace Operator",
        "email": "robert.wilson@mockcompany.com",
        "groups": [
            "SG-Production-Standard",
            "DL-AllEmployees", "DL-Production",
        ],
        "last_login": "2026-06-07T06:00:00",
        "m365_license": "Microsoft365_F3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 410,
        "ou": "OU=Users,OU=Kalamazoo,DC=mockcompany,DC=local",
        "location": "Kalamazoo",
        "manager": "cthompson",
        "created": "2023-01-09",
        "is_contractor": False,
    },
    # Big Rapids — Logistics (driver)
    "tpatel": {
        "status": "enabled",
        "full_name": "Tanya Patel",
        "department": "Logistics",
        "title": "Truck Driver",
        "email": "tanya.patel@mockcompany.com",
        "groups": [
            "SG-Logistics-Standard", "SG-Role-Driver",
            "DL-AllEmployees", "DL-Logistics",
        ],
        "last_login": "2026-06-08T05:30:00",
        "m365_license": "Microsoft365_F3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 220,
        "ou": "OU=Users,OU=BigRapids,DC=mockcompany,DC=local",
        "location": "Big Rapids",
        "manager": "cthompson",
        "created": "2024-02-14",
        "is_contractor": False,
    },
    # Grand Rapids — Supply Chain
    "mchen": {
        "status": "enabled",
        "full_name": "Michael Chen",
        "department": "Supply Chain",
        "title": "Purchasing Agent",
        "email": "michael.chen@mockcompany.com",
        "groups": [
            "SG-SupplyChain-Standard", "SG-Role-PurchasingAgent",
            "DL-AllEmployees", "DL-SupplyChain",
        ],
        "last_login": "2026-06-09T08:55:00",
        "m365_license": "Microsoft365_Business_Premium",
        "mailbox_enabled": True,
        "mailbox_size_mb": 1540,
        "ou": "OU=Users,OU=GrandRapids,DC=mockcompany,DC=local",
        "location": "Grand Rapids",
        "manager": "cthompson",
        "created": "2023-07-17",
        "is_contractor": False,
    },
    # Grand Rapids — Contractor example
    "jreyes-contractor": {
        "status": "enabled",
        "full_name": "Jose Reyes (Contractor)",
        "department": "Engineering",
        "title": "Contract Controls Engineer",
        "email": "jose.reyes@mockcompany.com",
        "groups": [
            "SG-Contractors", "SG-Engineering-Standard",
            "DL-AllEmployees",
        ],
        "last_login": "2026-06-06T11:00:00",
        "m365_license": "Microsoft365_F3",
        "mailbox_enabled": True,
        "mailbox_size_mb": 180,
        "ou": "OU=Users,OU=GrandRapids,DC=mockcompany,DC=local",
        "location": "Grand Rapids",
        "manager": "bmartinez",
        "created": "2026-01-06",
        "is_contractor": True,
    },
}

# ---------------------------------------------------------------------------
# M365 License inventory
# ---------------------------------------------------------------------------
_LICENSE_INVENTORY = {
    "Microsoft365_E5":               {"available": 8,  "total": 15},
    "Microsoft365_E3":               {"available": 42, "total": 75},
    "Microsoft365_F3":               {"available": 31, "total": 60},
    "Microsoft365_Business_Premium": {"available": 6,  "total": 10},
}

_LICENSE_SERVICES = {
    "Microsoft365_E5": [
        "Exchange Online P2", "SharePoint Online P2", "Microsoft Teams",
        "Intune Device Management", "Office Apps (Desktop + Mobile)",
        "Microsoft Defender for Endpoint P2", "Azure AD Premium P2",
        "Microsoft Purview (Compliance)", "Power BI Pro",
        "Microsoft Defender for Identity",
    ],
    "Microsoft365_E3": [
        "Exchange Online P1", "SharePoint Online P2", "Microsoft Teams",
        "Intune Device Management", "Office Apps (Desktop + Mobile)",
    ],
    "Microsoft365_F3": [
        "Exchange Online K1", "SharePoint Online F1",
        "Microsoft Teams Essentials", "Office Mobile Apps Only",
        "Intune (limited)",
    ],
    "Microsoft365_Business_Premium": [
        "Exchange Online P1", "SharePoint Online P1", "Microsoft Teams",
        "Intune Device Management", "Office Apps (Desktop + Mobile)",
        "Microsoft Defender for Business",
    ],
}


# =============================================================================
# TOOL HANDLERS
# Each function implements one MCP tool.
# All return dicts; execute_tool() serializes to JSON for the model.
# =============================================================================

def handle_get_onboarding_template(role: str) -> dict:
    role_key = role.lower().strip()

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
                    "Create AD account in MOCKCO domain (firstinitiallastname format)",
                    "Assign department-standard groups — call get_department_policies to determine correct groups",
                    "Provision Exchange mailbox — email format: firstname.lastname@mockcompany.com",
                    "Assign appropriate M365 license based on role (E5/E3/F3/Business Premium)",
                ],
                "day_one": [
                    "Security awareness and acceptable use policy acknowledgment",
                    "MFA enrollment (authenticator app; hardware key for IT/Executive roles)",
                    "Workstation and system access verification",
                ],
                "week_one": [
                    "Role-specific system training with manager",
                    "Review department policies and procedures",
                    "Introduction to key contacts and team members",
                ],
            },
            "requires_background_check": False,
            "admin_account_required": False,
            "security_clearance": "Standard",
            "license_tier": "Unknown — determine from role and department",
            "note": (
                f"No specific template found for '{role}'. Generic MOCKCO template returned. "
                "Consult HR and the hiring manager for role-specific requirements."
            ),
        }

    return {
        "role": role,
        "template_matched": "note" not in template,
        "template": template,
        "retrieved_at": datetime.now().isoformat(),
        "source": "MOCKCO HR-IT Onboarding Policy v3.1",
        "domain": _NETBIOS,
    }


def handle_get_department_policies(department: str) -> dict:
    dept_stripped = department.strip()
    policy = _DEPARTMENT_POLICIES.get(dept_stripped) or _DEPARTMENT_POLICIES.get(dept_stripped.title())
    dept_key = dept_stripped if _DEPARTMENT_POLICIES.get(dept_stripped) else dept_stripped.title()

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
            "error": (
                f"No policy configuration found for department '{department}'. "
                "Verify spelling or contact IT."
            ),
            "available_departments": list(_DEPARTMENT_POLICIES.keys()),
        }

    return {
        "department": dept_key,
        "found": True,
        "policies": policy,
        "ou_note": (
            "MOCKCO OUs are location-based, not department-based. "
            "OU placement is determined by the employee's work site: "
            "Holland, Grand Rapids, Kalamazoo, or Big Rapids."
        ),
        "retrieved_at": datetime.now().isoformat(),
        "source": "MOCKCO IT Security Policy Framework v2.4",
        "domain": _NETBIOS,
    }


def handle_create_ad_user(
    first_name: str,
    last_name: str,
    department: str,
    job_title: str,
    location: str = "Grand Rapids",
    manager: str = None,
    start_date: str = None,
    is_contractor: bool = False,
) -> dict:
    # Build username: firstinitiallastname (all lowercase, no spaces)
    base_username = (first_name[0] + last_name).lower().replace(" ", "").replace("-", "")
    if is_contractor:
        base_username = base_username + "-contractor"

    username = base_username
    counter = 2
    while username in _AD_USERS_DB:
        username = f"{base_username}{counter}"
        counter += 1

    # Email is firstname.lastname@mockcompany.com (not username-based)
    email = f"{first_name.lower()}.{last_name.lower()}@{_EMAIL_DOMAIN}"

    # UPN matches email domain per MOCKCO convention
    upn = email

    # OU is location-based
    normalized_location = location.strip().title()
    ou = _LOCATION_OUS.get(normalized_location, _LOCATION_OUS["Grand Rapids"])
    if normalized_location not in _LOCATION_OUS:
        normalized_location = "Grand Rapids"
        ou = _LOCATION_OUS["Grand Rapids"]

    temp_password = f"Mockco1!{random.randint(100, 999)}"

    _AD_USERS_DB[username] = {
        "status": "enabled",
        "full_name": f"{first_name} {last_name}",
        "department": department,
        "title": job_title,
        "email": email,
        "groups": ["DL-AllEmployees"],
        "last_login": None,
        "m365_license": None,
        "mailbox_enabled": False,
        "mailbox_size_mb": 0,
        "ou": ou,
        "location": normalized_location,
        "created": datetime.now().isoformat(),
        "manager": manager,
        "is_contractor": is_contractor,
    }

    result = {
        "success": True,
        "action": "AD_USER_CREATED",
        "username": username,
        "upn": upn,
        "email": email,
        "display_name": f"{first_name} {last_name}",
        "department": department,
        "job_title": job_title,
        "location": normalized_location,
        "ou_path": ou,
        "domain": _NETBIOS,
        "netbios_logon": f"{_NETBIOS}\\{username}",
        "manager": manager or "Not specified",
        "start_date": start_date or "Not specified",
        "is_contractor": is_contractor,
        "temporary_password": temp_password,
        "password_change_required": True,
        "created_at": datetime.now().isoformat(),
        "note": (
            "Account created in MOCKCO domain. "
            "Note: email format is firstname.lastname@mockcompany.com. "
            "Password must be changed on first login. MFA enrollment required within 24 hours."
        ),
    }

    # Auto-create admin account for IT roles
    dept_policy = _DEPARTMENT_POLICIES.get(department.strip()) or \
                  _DEPARTMENT_POLICIES.get(department.strip().title(), {})
    if dept_policy.get("admin_account_required") and not is_contractor:
        admin_username = f"{username}-admin"
        _AD_USERS_DB[admin_username] = {
            "status": "enabled",
            "full_name": f"{first_name} {last_name} (Admin)",
            "department": department,
            "title": f"{job_title} — Privileged Account",
            "email": None,
            "groups": ["SG-IT-Full", "Domain Admins"],
            "last_login": None,
            "m365_license": None,
            "mailbox_enabled": False,
            "mailbox_size_mb": 0,
            "ou": _ADMIN_OU,
            "location": normalized_location,
            "created": datetime.now().isoformat(),
            "manager": username,
            "is_contractor": False,
            "admin_account": True,
        }
        result["admin_account_created"] = True
        result["admin_username"] = admin_username
        result["admin_ou"] = _ADMIN_OU
        result["admin_note"] = (
            f"Privileged admin account '{admin_username}' created in OU=Admins. "
            "Per MOCKCO policy, IT staff use separate accounts for privileged operations."
        )

    return result


def handle_assign_ad_groups(username: str, groups: list) -> dict:
    if username not in _AD_USERS_DB:
        return {
            "success": False,
            "error": (
                f"User '{username}' not found in MOCKCO Active Directory. "
                "Verify username with get_user_status."
            ),
        }

    assigned = []
    failed = []

    for group in groups:
        if "INVALID" in group.upper() or "NOTEXIST" in group.upper():
            failed.append({"group": group, "error": "Group not found in MOCKCO Active Directory"})
        else:
            if group not in _AD_USERS_DB[username]["groups"]:
                _AD_USERS_DB[username]["groups"].append(group)
            assigned.append({
                "group": group,
                "status": "assigned",
                "type": "Distribution List" if group.startswith("DL-") else "Security Group",
            })

    return {
        "success": len(failed) == 0,
        "partial_success": len(assigned) > 0 and len(failed) > 0,
        "action": "AD_GROUPS_ASSIGNED",
        "username": username,
        "domain": _NETBIOS,
        "groups_assigned": assigned,
        "groups_failed": failed,
        "total_assigned": len(assigned),
        "current_group_memberships": _AD_USERS_DB[username]["groups"],
        "completed_at": datetime.now().isoformat(),
    }


def handle_provision_exchange_mailbox(username: str, mailbox_type: str = "UserMailbox") -> dict:
    if username not in _AD_USERS_DB:
        return {
            "success": False,
            "error": f"User '{username}' not found in MOCKCO Active Directory.",
        }

    if _AD_USERS_DB[username]["mailbox_enabled"]:
        return {
            "success": False,
            "already_exists": True,
            "username": username,
            "email": _AD_USERS_DB[username]["email"],
            "message": "Mailbox already provisioned for this user.",
        }

    _AD_USERS_DB[username]["mailbox_enabled"] = True
    email = _AD_USERS_DB[username]["email"]

    return {
        "success": True,
        "action": "EXCHANGE_MAILBOX_PROVISIONED",
        "username": username,
        "email_address": email,
        "mailbox_type": mailbox_type,
        "exchange_server": "EXCH-MOCKCO-01.mockcompany.local",
        "routing_mode": "Hybrid (On-Prem Exchange → Exchange Online)",
        "database": "MailboxDB-GR-01",
        "quota_mb": 51200,
        "archive_enabled": False,
        "smtp_addresses": [
            email,
            f"{username}@mockcompany.onmicrosoft.com",
        ],
        "provisioned_at": datetime.now().isoformat(),
        "aad_connect_sync_eta": "~30 minutes",
        "note": (
            "Mailbox enabled on EXCH-MOCKCO-01. "
            "Email routing active after next AAD Connect sync (~30 min). "
            f"Primary SMTP: {email}"
        ),
    }


def handle_assign_m365_license(username: str, license_type: str) -> dict:
    if username not in _AD_USERS_DB:
        return {
            "success": False,
            "error": f"User '{username}' not found in MOCKCO Active Directory.",
        }

    if not _AD_USERS_DB[username]["mailbox_enabled"]:
        return {
            "success": False,
            "error": "Exchange mailbox must be provisioned before assigning an M365 license.",
            "recommendation": "Call provision_exchange_mailbox first, then retry.",
        }

    if _AD_USERS_DB[username].get("m365_license"):
        return {
            "success": False,
            "already_assigned": True,
            "username": username,
            "current_license": _AD_USERS_DB[username]["m365_license"],
            "message": "License already assigned. Use M365 admin portal to change or upgrade.",
        }

    inventory = _LICENSE_INVENTORY.get(license_type, {})
    if inventory.get("available", 0) == 0:
        return {
            "success": False,
            "error": f"No available licenses for {license_type}. Contact IT Procurement.",
            "licenses_available": 0,
            "licenses_total": inventory.get("total", 0),
        }

    _AD_USERS_DB[username]["m365_license"] = license_type
    _LICENSE_INVENTORY[license_type]["available"] -= 1

    return {
        "success": True,
        "action": "M365_LICENSE_ASSIGNED",
        "username": username,
        "email": _AD_USERS_DB[username]["email"],
        "license_assigned": license_type,
        "services_enabled": _LICENSE_SERVICES.get(license_type, []),
        "licenses_remaining": _LICENSE_INVENTORY[license_type]["available"],
        "tenant": "mockcompany.onmicrosoft.com",
        "activation_eta": "~15–30 minutes",
        "assigned_at": datetime.now().isoformat(),
        "note": "License assigned. Services will activate within 15–30 minutes.",
    }


def handle_disable_ad_user(
    username: str,
    reason: str,
    move_to_disabled_ou: bool = True,
) -> dict:
    found_username = _find_user(username)
    if not found_username:
        return {
            "success": False,
            "error": f"User '{username}' not found in MOCKCO Active Directory.",
            "suggestion": "Use get_user_status to verify the username.",
        }

    if _AD_USERS_DB[found_username]["status"] == "disabled":
        return {
            "success": False,
            "already_disabled": True,
            "username": found_username,
            "message": f"Account '{found_username}' is already disabled.",
            "disabled_since": _AD_USERS_DB[found_username].get("disabled_at", "Unknown"),
        }

    previous_ou = _AD_USERS_DB[found_username]["ou"]
    _AD_USERS_DB[found_username]["status"] = "disabled"
    _AD_USERS_DB[found_username]["disabled_at"] = datetime.now().isoformat()
    _AD_USERS_DB[found_username]["disabled_reason"] = reason

    if move_to_disabled_ou:
        _AD_USERS_DB[found_username]["ou"] = _DISABLED_OU

    return {
        "success": True,
        "action": "AD_USER_DISABLED",
        "username": found_username,
        "full_name": _AD_USERS_DB[found_username]["full_name"],
        "domain": _NETBIOS,
        "previous_status": "enabled",
        "new_status": "disabled",
        "reason": reason,
        "password_reset": True,
        "moved_to_disabled_ou": move_to_disabled_ou,
        "previous_ou": previous_ou,
        "new_ou": _AD_USERS_DB[found_username]["ou"],
        "all_sessions_terminated": True,
        "logon_blocked": True,
        "disabled_at": _AD_USERS_DB[found_username]["disabled_at"],
        "performed_by": "MOCKCO-IT-Automation",
        "note": (
            "Account disabled and password reset. "
            "All active Kerberos sessions terminated. "
            "Account moved to Disabled Users OU."
        ),
    }


def handle_revoke_access(
    username: str,
    scope: str = "all",
    emergency: bool = False,
    offboard_type: str = "resignation",
    delegate_to: str = None,
) -> dict:
    found_username = _find_user(username)
    if not found_username:
        return {
            "success": False,
            "error": f"User '{username}' not found in MOCKCO Active Directory.",
        }

    user = _AD_USERS_DB[found_username]
    removed_groups = [g for g in user["groups"] if g not in ("DL-AllEmployees",)]
    actions_taken = []

    if scope in ("all", "groups_only"):
        _AD_USERS_DB[found_username]["groups"] = ["DL-AllEmployees"]
        actions_taken.append({
            "action": "AD_GROUPS_REMOVED",
            "detail": f"Removed from {len(removed_groups)} security groups and distribution lists",
            "groups_removed": removed_groups,
        })

    if scope in ("all", "m365_only"):
        prev_license = _AD_USERS_DB[found_username].get("m365_license")
        _AD_USERS_DB[found_username]["m365_license"] = None
        if prev_license and prev_license in _LICENSE_INVENTORY:
            _LICENSE_INVENTORY[prev_license]["available"] += 1
        actions_taken.append({
            "action": "M365_LICENSE_REVOKED",
            "detail": (
                f"License {prev_license or 'none'} removed. "
                "All Azure AD and M365 sessions invalidated. "
                "Block sign-in applied in Azure AD."
            ),
        })

    if scope in ("all", "vpn_only"):
        actions_taken.append({
            "action": "VPN_ACCESS_REVOKED",
            "detail": "VPN access revoked in network policy. Active VPN sessions dropped.",
        })

    if scope == "all":
        # Mailbox disposition depends on offboard type
        if offboard_type == "resignation":
            mailbox_action = (
                f"Mailbox converted to SharedMailbox. "
                f"Delegate access granted to {delegate_to or 'HR (slopez)'}. "
                "Email forwarding enabled per manager request (30-day default)."
            )
        else:
            # Termination or security incident — no forwarding
            mailbox_action = (
                "Mailbox converted to SharedMailbox. "
                "No email forwarding enabled (termination/security policy). "
                f"Delegate access granted to {delegate_to or 'HR (slopez)'} for records retention."
            )

        actions_taken.extend([
            {
                "action": "MAILBOX_CONVERTED_TO_SHARED",
                "detail": mailbox_action,
            },
            {
                "action": "ONEDRIVE_ACCESS_TRANSFERRED",
                "detail": (
                    f"OneDrive content access transferred to "
                    f"{delegate_to or 'manager or HR'}. "
                    "Retention period: 30 days per MOCKCO policy."
                ),
            },
            {
                "action": "MFA_TOKENS_INVALIDATED",
                "detail": "All registered MFA devices and authenticator tokens revoked.",
            },
            {
                "action": "AZURE_AD_SIGNIN_BLOCKED",
                "detail": "Block sign-in policy applied in Azure AD / Entra ID.",
            },
            {
                "action": "EMAIL_DELEGATIONS_REMOVED",
                "detail": "All Send-As and Full Access mailbox delegations removed.",
            },
        ])

        if offboard_type == "termination":
            actions_taken.append({
                "action": "EMAIL_FORWARDING_BLOCKED",
                "detail": (
                    "Email auto-forward rules disabled. "
                    "External forwarding blocked per termination policy."
                ),
            })

        if emergency or offboard_type == "security_incident":
            actions_taken.append({
                "action": "INCIDENT_RESPONSE_TRIGGERED",
                "detail": (
                    "Security team notified via INC ticket. "
                    "Account flagged for forensic review. "
                    "Azure AD sign-in logs exported. "
                    "Endpoint isolation initiated via Defender for Endpoint."
                ),
            })

    audit_ticket = f"INC-MOCKCO-{random.randint(10000, 99999)}"

    return {
        "success": True,
        "action": "ACCESS_REVOKED",
        "username": found_username,
        "full_name": user["full_name"],
        "domain": _NETBIOS,
        "scope": scope,
        "offboard_type": offboard_type,
        "emergency_mode": emergency,
        "priority": "IMMEDIATE" if (emergency or offboard_type == "security_incident") else "STANDARD",
        "actions_taken": actions_taken,
        "total_actions": len(actions_taken),
        "audit_ticket": audit_ticket,
        "completed_at": datetime.now().isoformat(),
        "note": (
            f"Access revocation complete. "
            f"Audit ticket {audit_ticket} created for MOCKCO compliance records. "
            "IT Manager and HR have been notified."
        ),
    }


def handle_get_user_status(username: str) -> dict:
    found_username = _find_user(username)

    if not found_username:
        return {
            "found": False,
            "searched": username,
            "domain": _NETBIOS,
            "error": "User not found in MOCKCO Active Directory.",
            "suggestion": (
                "Verify the sAMAccountName or try a partial full name search. "
                "Username format is firstinitiallastname (e.g. jdoe)."
            ),
        }

    user = _AD_USERS_DB[found_username]
    return {
        "found": True,
        "username": found_username,
        "domain": _NETBIOS,
        "netbios_logon": f"{_NETBIOS}\\{found_username}",
        "full_name": user.get("full_name"),
        "status": user["status"],
        "department": user.get("department"),
        "title": user.get("title"),
        "email": user.get("email"),
        "location": user.get("location"),
        "ou_path": user.get("ou"),
        "manager": user.get("manager"),
        "is_contractor": user.get("is_contractor", False),
        "admin_account": user.get("admin_account", False),
        "groups": user.get("groups", []),
        "group_count": len(user.get("groups", [])),
        "last_login": user.get("last_login"),
        "m365_license": user.get("m365_license"),
        "mailbox_enabled": user.get("mailbox_enabled", False),
        "mailbox_size_mb": user.get("mailbox_size_mb") if user.get("mailbox_enabled") else None,
        "created": user.get("created"),
        "disabled_at": user.get("disabled_at"),
        "disabled_reason": user.get("disabled_reason"),
        "retrieved_at": datetime.now().isoformat(),
    }


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _find_user(query: str) -> str | None:
    """Return sAMAccountName for a query string (exact username or partial full name)."""
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
# The agent loop calls execute_tool() with the name and input from each
# tool_use block in the model's response.
# =============================================================================

_TOOL_HANDLERS = {
    "get_onboarding_template":   handle_get_onboarding_template,
    "get_department_policies":   handle_get_department_policies,
    "create_ad_user":            handle_create_ad_user,
    "assign_ad_groups":          handle_assign_ad_groups,
    "provision_exchange_mailbox": handle_provision_exchange_mailbox,
    "assign_m365_license":       handle_assign_m365_license,
    "disable_ad_user":           handle_disable_ad_user,
    "revoke_access":             handle_revoke_access,
    "get_user_status":           handle_get_user_status,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Dispatch a model-requested tool call to the correct handler.
    Always returns a JSON string — errors are JSON too so the model
    can reason about failures and decide what to do next.
    """
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({
            "error": f"Unknown tool: '{tool_name}'",
            "available_tools": list(_TOOL_HANDLERS.keys()),
        })

    try:
        result = handler(**tool_input)
        return json.dumps(result, indent=2, default=str)
    except TypeError as e:
        return json.dumps({
            "error": f"Invalid parameters for tool '{tool_name}': {e}",
            "received_input": tool_input,
        })
    except Exception as e:
        return json.dumps({
            "error": f"Tool execution error in '{tool_name}': {e}",
            "tool": tool_name,
        })