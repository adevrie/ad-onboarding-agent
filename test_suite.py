"""
test_suite.py — Unit and integration tests for the MOCKCO IT Workflow Orchestrator.

Unit tests exercise the tool-handler layer directly (no API calls, no cost).
Agent integration tests run the full agentic loop against the live API.

Usage:
    python test_suite.py --unit     # Tool-layer tests only (~5 seconds, no API)
    python test_suite.py --agent    # Agent integration tests (requires ANTHROPIC_API_KEY)
    python test_suite.py            # Both suites
"""

import argparse
import copy
import json
import sys
import unittest

import tools as tools_module
from tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    handle_assign_ad_groups,
    handle_assign_m365_license,
    handle_create_ad_user,
    handle_disable_ad_user,
    handle_get_department_policies,
    handle_get_onboarding_template,
    handle_get_user_status,
    handle_provision_exchange_mailbox,
    handle_revoke_access,
)


# =============================================================================
# Base class — isolates _AD_USERS_DB and _LICENSE_INVENTORY between tests
# =============================================================================

class ToolTestCase(unittest.TestCase):
    """Saves and restores module-level mock state so each test starts clean."""

    def setUp(self):
        self._saved_users = copy.deepcopy(tools_module._AD_USERS_DB)
        self._saved_licenses = copy.deepcopy(tools_module._LICENSE_INVENTORY)

    def tearDown(self):
        tools_module._AD_USERS_DB.clear()
        tools_module._AD_USERS_DB.update(self._saved_users)
        tools_module._LICENSE_INVENTORY.clear()
        tools_module._LICENSE_INVENTORY.update(self._saved_licenses)


# =============================================================================
# UNIT TESTS — tool layer, no API calls
# =============================================================================

class TestToolDefinitions(unittest.TestCase):

    def test_nine_tools_defined(self):
        self.assertEqual(len(TOOL_DEFINITIONS), 9)

    def test_all_tools_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            with self.subTest(tool=tool.get("name")):
                self.assertIn("name", tool)
                self.assertIn("description", tool)
                self.assertIn("input_schema", tool)
                self.assertIn("required", tool["input_schema"])

    def test_tool_names(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "get_onboarding_template", "get_department_policies",
            "create_ad_user", "assign_ad_groups", "provision_exchange_mailbox",
            "assign_m365_license", "disable_ad_user", "revoke_access",
            "get_user_status",
        }
        self.assertEqual(names, expected)


class TestOnboardingTemplate(ToolTestCase):

    def test_known_role_returns_match(self):
        result = handle_get_onboarding_template("IT Admin")
        self.assertTrue(result["template_matched"])
        self.assertIn("pre_day_one", result["template"]["phases"])

    def test_case_insensitive_match(self):
        result = handle_get_onboarding_template("it admin")
        self.assertTrue(result["template_matched"])

    def test_unknown_role_returns_generic_template(self):
        result = handle_get_onboarding_template("Underwater Basket Weaver")
        self.assertFalse(result["template_matched"])
        self.assertIn("note", result["template"])

    def test_it_admin_requires_admin_account(self):
        result = handle_get_onboarding_template("IT Admin")
        self.assertTrue(result["template"]["admin_account_required"])

    def test_hr_generalist_e3_license(self):
        result = handle_get_onboarding_template("HR Generalist")
        self.assertEqual(result["template"]["license_tier"], "Microsoft365_E3")

    def test_purchasing_agent_business_premium(self):
        result = handle_get_onboarding_template("Purchasing Agent")
        self.assertEqual(result["template"]["license_tier"], "Microsoft365_Business_Premium")

    def test_truck_driver_f3_license(self):
        result = handle_get_onboarding_template("Truck Driver")
        self.assertEqual(result["template"]["license_tier"], "Microsoft365_F3")


class TestDepartmentPolicies(ToolTestCase):

    def test_exact_match(self):
        result = handle_get_department_policies("IT")
        self.assertTrue(result["found"])
        self.assertEqual(result["department"], "IT")

    def test_hr_case_insensitive(self):
        # Regression: v1 bug converted "HR" → "Hr" via .title(), breaking lookup
        result = handle_get_department_policies("HR")
        self.assertTrue(result["found"])

    def test_lowercase_input_resolves(self):
        result = handle_get_department_policies("engineering")
        self.assertTrue(result["found"])

    def test_unknown_department_returns_not_found(self):
        result = handle_get_department_policies("Underwater Basket Weaving")
        self.assertFalse(result["found"])
        self.assertIn("available_departments", result)

    def test_it_policy_requires_admin_account(self):
        result = handle_get_department_policies("IT")
        self.assertTrue(result["policies"]["admin_account_required"])

    def test_production_f3_license(self):
        result = handle_get_department_policies("Production")
        self.assertEqual(result["policies"]["default_license"], "Microsoft365_F3")

    def test_supply_chain_business_premium(self):
        result = handle_get_department_policies("Supply Chain")
        self.assertEqual(result["policies"]["default_license"], "Microsoft365_Business_Premium")

    def test_operations_e5_license(self):
        result = handle_get_department_policies("Operations")
        self.assertEqual(result["policies"]["default_license"], "Microsoft365_E5")


class TestCreateAdUser(ToolTestCase):

    def test_username_format_firstinitiallastname(self):
        result = handle_create_ad_user("Alice", "Smith", "HR", "HR Generalist", "Holland")
        self.assertEqual(result["username"], "asmith")

    def test_email_format(self):
        result = handle_create_ad_user("Alice", "Smith", "HR", "HR Generalist", "Holland")
        self.assertEqual(result["email"], "alice.smith@mockcompany.com")

    def test_holland_ou_placement(self):
        result = handle_create_ad_user("Alice", "Smith", "HR", "HR Generalist", "Holland")
        self.assertIn("OU=Holland", result["ou_path"])

    def test_grand_rapids_ou_placement(self):
        result = handle_create_ad_user("Bob", "Jones", "Engineering", "Engineer", "Grand Rapids")
        self.assertIn("OU=GrandRapids", result["ou_path"])

    def test_kalamazoo_ou_placement(self):
        result = handle_create_ad_user("Carol", "King", "Production", "Furnace Operator", "Kalamazoo")
        self.assertIn("OU=Kalamazoo", result["ou_path"])

    def test_big_rapids_ou_placement(self):
        result = handle_create_ad_user("Dave", "Lee", "Logistics", "Truck Driver", "Big Rapids")
        self.assertIn("OU=BigRapids", result["ou_path"])

    def test_unknown_location_defaults_to_grand_rapids(self):
        result = handle_create_ad_user("Eve", "Brown", "HR", "HR Generalist", "Narnia")
        self.assertIn("OU=GrandRapids", result["ou_path"])

    def test_duplicate_username_gets_numeric_suffix(self):
        # slopez already exists in seed data
        handle_create_ad_user("Sandra", "Lopez", "HR", "HR Generalist", "Holland")
        self.assertIn("slopez2", tools_module._AD_USERS_DB)

    def test_it_dept_auto_creates_admin_account(self):
        result = handle_create_ad_user("Jamie", "Torres", "IT", "IT Admin", "Grand Rapids")
        self.assertTrue(result.get("admin_account_created"))
        admin_username = result["admin_username"]
        self.assertIn(admin_username, tools_module._AD_USERS_DB)
        self.assertEqual(
            tools_module._AD_USERS_DB[admin_username]["ou"],
            "OU=Admins,DC=mockcompany,DC=local",
        )

    def test_admin_account_has_no_mailbox_or_license(self):
        result = handle_create_ad_user("Jamie", "Torres", "IT", "IT Admin", "Grand Rapids")
        admin = tools_module._AD_USERS_DB[result["admin_username"]]
        self.assertFalse(admin["mailbox_enabled"])
        self.assertIsNone(admin["m365_license"])

    def test_user_persisted_in_db(self):
        result = handle_create_ad_user("New", "User", "Engineering", "Process Engineer", "Holland")
        self.assertIn(result["username"], tools_module._AD_USERS_DB)

    def test_contractor_username_suffix(self):
        result = handle_create_ad_user(
            "Jose", "Reyes", "Engineering", "Contract Engineer", "Grand Rapids",
            is_contractor=True,
        )
        self.assertIn("-contractor", result["username"])

    def test_non_it_dept_does_not_create_admin_account(self):
        result = handle_create_ad_user("Alice", "Smith", "HR", "HR Generalist", "Holland")
        self.assertFalse(result.get("admin_account_created", False))


class TestAssignAdGroups(ToolTestCase):

    def test_assign_groups_to_existing_user(self):
        result = handle_assign_ad_groups("slopez", ["SG-HR-Full", "DL-HR"])
        self.assertTrue(result["success"])

    def test_groups_persisted_in_db(self):
        handle_assign_ad_groups("bmartinez", ["SG-NewGroup"])
        self.assertIn("SG-NewGroup", tools_module._AD_USERS_DB["bmartinez"]["groups"])

    def test_unknown_user_returns_failure(self):
        result = handle_assign_ad_groups("doesnotexist", ["SG-IT-Full"])
        self.assertFalse(result["success"])

    def test_invalid_group_goes_to_failed_list(self):
        result = handle_assign_ad_groups("slopez", ["SG-INVALID-NOTEXIST"])
        self.assertGreater(len(result["groups_failed"]), 0)

    def test_total_assigned_count(self):
        result = handle_assign_ad_groups("bmartinez", ["SG-A", "SG-B", "SG-C"])
        self.assertEqual(result["total_assigned"], 3)


class TestProvisionMailbox(ToolTestCase):

    def _new_user(self) -> str:
        return handle_create_ad_user("Test", "User", "HR", "HR Generalist", "Holland")["username"]

    def test_provision_mailbox_success(self):
        username = self._new_user()
        result = handle_provision_exchange_mailbox(username)
        self.assertTrue(result["success"])
        self.assertTrue(tools_module._AD_USERS_DB[username]["mailbox_enabled"])

    def test_already_provisioned_returns_error(self):
        # slopez has mailbox_enabled=True in seed data
        result = handle_provision_exchange_mailbox("slopez")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("already_exists"))

    def test_unknown_user_returns_error(self):
        result = handle_provision_exchange_mailbox("doesnotexist")
        self.assertFalse(result["success"])

    def test_email_address_in_result(self):
        username = self._new_user()
        result = handle_provision_exchange_mailbox(username)
        self.assertIn("@mockcompany.com", result["email_address"])


class TestAssignM365License(ToolTestCase):

    def _user_with_mailbox(self) -> str:
        username = handle_create_ad_user("Test", "License", "Engineering", "Engineer", "Holland")["username"]
        handle_provision_exchange_mailbox(username)
        return username

    def test_assign_license_success(self):
        username = self._user_with_mailbox()
        result = handle_assign_m365_license(username, "Microsoft365_E3")
        self.assertTrue(result["success"])
        self.assertEqual(tools_module._AD_USERS_DB[username]["m365_license"], "Microsoft365_E3")

    def test_license_inventory_decremented(self):
        before = tools_module._LICENSE_INVENTORY["Microsoft365_E3"]["available"]
        username = self._user_with_mailbox()
        handle_assign_m365_license(username, "Microsoft365_E3")
        after = tools_module._LICENSE_INVENTORY["Microsoft365_E3"]["available"]
        self.assertEqual(after, before - 1)

    def test_fails_without_mailbox(self):
        username = handle_create_ad_user("No", "Mailbox", "Engineering", "Engineer", "Holland")["username"]
        result = handle_assign_m365_license(username, "Microsoft365_E3")
        self.assertFalse(result["success"])
        self.assertIn("mailbox", result["error"].lower())

    def test_fails_for_unknown_user(self):
        result = handle_assign_m365_license("doesnotexist", "Microsoft365_E3")
        self.assertFalse(result["success"])

    def test_already_assigned_returns_error(self):
        # slopez already has E3 in seed data
        result = handle_assign_m365_license("slopez", "Microsoft365_E3")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("already_assigned"))


class TestDisableAdUser(ToolTestCase):

    def test_disable_existing_user(self):
        result = handle_disable_ad_user("bmartinez", "Voluntary resignation")
        self.assertTrue(result["success"])
        self.assertEqual(tools_module._AD_USERS_DB["bmartinez"]["status"], "disabled")

    def test_moved_to_disabled_ou(self):
        handle_disable_ad_user("bmartinez", "Voluntary resignation")
        self.assertIn("Disabled Users", tools_module._AD_USERS_DB["bmartinez"]["ou"])

    def test_already_disabled_returns_error(self):
        handle_disable_ad_user("bmartinez", "First disable")
        result = handle_disable_ad_user("bmartinez", "Second attempt")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("already_disabled"))

    def test_unknown_user_returns_error(self):
        result = handle_disable_ad_user("doesnotexist", "Test")
        self.assertFalse(result["success"])

    def test_partial_name_lookup(self):
        # "Sandra Lopez" should resolve to slopez
        result = handle_disable_ad_user("Sandra Lopez", "Resignation")
        self.assertTrue(result["success"])
        self.assertEqual(tools_module._AD_USERS_DB["slopez"]["status"], "disabled")


class TestRevokeAccess(ToolTestCase):

    def test_revoke_removes_groups(self):
        groups_before = len(tools_module._AD_USERS_DB["slopez"]["groups"])
        handle_revoke_access("slopez", offboard_type="resignation")
        groups_after = len(tools_module._AD_USERS_DB["slopez"]["groups"])
        self.assertLess(groups_after, groups_before)

    def test_revoke_returns_license_to_inventory(self):
        before = tools_module._LICENSE_INVENTORY["Microsoft365_E3"]["available"]
        handle_revoke_access("slopez", offboard_type="resignation")
        after = tools_module._LICENSE_INVENTORY["Microsoft365_E3"]["available"]
        self.assertEqual(after, before + 1)

    def test_resignation_enables_forwarding(self):
        result = handle_revoke_access("slopez", offboard_type="resignation")
        mailbox_action = next(
            a for a in result["actions_taken"] if a["action"] == "MAILBOX_CONVERTED_TO_SHARED"
        )
        self.assertIn("forwarding", mailbox_action["detail"].lower())

    def test_termination_blocks_forwarding(self):
        result = handle_revoke_access("slopez", offboard_type="termination")
        action_names = [a["action"] for a in result["actions_taken"]]
        self.assertIn("EMAIL_FORWARDING_BLOCKED", action_names)
        mailbox_action = next(
            a for a in result["actions_taken"] if a["action"] == "MAILBOX_CONVERTED_TO_SHARED"
        )
        # "no email forwarding" should appear; "auto-enabled" or similar should not
        self.assertIn("no email forwarding", mailbox_action["detail"].lower())

    def test_security_incident_triggers_incident_response(self):
        result = handle_revoke_access("rwilson", emergency=True, offboard_type="security_incident")
        action_names = [a["action"] for a in result["actions_taken"]]
        self.assertIn("INCIDENT_RESPONSE_TRIGGERED", action_names)

    def test_security_incident_priority_is_immediate(self):
        result = handle_revoke_access("rwilson", emergency=True, offboard_type="security_incident")
        self.assertEqual(result["priority"], "IMMEDIATE")

    def test_standard_offboard_priority_is_standard(self):
        result = handle_revoke_access("slopez", offboard_type="resignation")
        self.assertEqual(result["priority"], "STANDARD")

    def test_unknown_user_returns_failure(self):
        result = handle_revoke_access("doesnotexist")
        self.assertFalse(result["success"])

    def test_audit_ticket_generated(self):
        result = handle_revoke_access("tpatel", offboard_type="resignation")
        self.assertTrue(result["audit_ticket"].startswith("INC-MOCKCO-"))


class TestGetUserStatus(ToolTestCase):

    def test_lookup_by_username(self):
        result = handle_get_user_status("slopez")
        self.assertTrue(result["found"])
        self.assertEqual(result["username"], "slopez")

    def test_lookup_by_partial_name(self):
        result = handle_get_user_status("Sandra Lopez")
        self.assertTrue(result["found"])
        self.assertEqual(result["username"], "slopez")

    def test_unknown_user_returns_not_found(self):
        result = handle_get_user_status("nobody_here_xyz")
        self.assertFalse(result["found"])

    def test_required_fields_present(self):
        result = handle_get_user_status("slopez")
        for field in ("status", "department", "location", "groups", "m365_license", "mailbox_enabled"):
            with self.subTest(field=field):
                self.assertIn(field, result)

    def test_contractor_flag_correct(self):
        result = handle_get_user_status("jreyes-contractor")
        self.assertTrue(result["is_contractor"])

    def test_admin_account_flag_correct(self):
        result = handle_get_user_status("adevries-admin")
        self.assertTrue(result["admin_account"])


class TestToolDispatcher(ToolTestCase):

    def test_unknown_tool_returns_error(self):
        result = json.loads(execute_tool("nonexistent_tool", {}))
        self.assertIn("error", result)

    def test_dispatch_get_user_status(self):
        result = json.loads(execute_tool("get_user_status", {"username": "slopez"}))
        self.assertTrue(result["found"])

    def test_dispatch_with_missing_required_params_returns_error(self):
        # create_ad_user requires first_name, last_name, department, job_title, location
        result = json.loads(execute_tool("create_ad_user", {"first_name": "Only"}))
        self.assertIn("error", result)

    def test_dispatch_get_department_policies(self):
        result = json.loads(execute_tool("get_department_policies", {"department": "IT"}))
        self.assertTrue(result["found"])


class TestOuPlacementRegression(ToolTestCase):
    """Regression tests for the tools.py v1 .title() normalization bug.

    In v1, department.title() converted "HR" to "Hr", failing the _DEPARTMENT_POLICIES
    dict lookup and falling through to a generic OU fallback. Fixed in v2 by trying
    exact match first, then falling back to .title().
    """

    def test_hr_department_resolves_exactly(self):
        result = handle_get_department_policies("HR")
        self.assertTrue(result["found"])
        self.assertEqual(result["department"], "HR")

    def test_it_department_resolves_exactly(self):
        result = handle_get_department_policies("IT")
        self.assertTrue(result["found"])
        self.assertEqual(result["department"], "IT")

    def test_onboarding_hr_user_gets_correct_location_ou(self):
        # If HR dept lookup broke, user would land in fallback OU instead of Holland
        result = handle_create_ad_user("Test", "HrBug", "HR", "HR Generalist", "Holland")
        self.assertIn("OU=Holland", result["ou_path"])
        self.assertNotIn("General", result["ou_path"])


# =============================================================================
# AGENT INTEGRATION TESTS — requires ANTHROPIC_API_KEY, makes real API calls
# =============================================================================

class TestAgentIntegration(ToolTestCase):

    @classmethod
    def setUpClass(cls):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise unittest.SkipTest("ANTHROPIC_API_KEY not set — skipping agent integration tests")
        from agent import OnboardingAgent
        cls.agent = OnboardingAgent()

    def setUp(self):
        super().setUp()
        self.agent.reset()

    def test_status_check_returns_user_info(self):
        response = self.agent.run("What is the current status of Sandra Lopez?")
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 50)
        # User should not have been mutated
        self.assertEqual(tools_module._AD_USERS_DB["slopez"]["status"], "enabled")

    def test_onboarding_creates_user_in_correct_ou(self):
        response = self.agent.run(
            "Onboard a new HR Generalist named Quinn Testuser in Holland"
        )
        created = [u for u in tools_module._AD_USERS_DB if u.startswith("qtest")]
        self.assertGreater(len(created), 0, "Expected agent to create a user for Quinn Testuser")
        ou = tools_module._AD_USERS_DB[created[0]]["ou"]
        self.assertIn("OU=Holland", ou)

    def test_unknown_user_status_handled_gracefully(self):
        response = self.agent.run("Check the status of nobody_here_xyz_99999")
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)
        # Agent should not have crashed or returned an empty string


# =============================================================================
# Entry point
# =============================================================================

def build_suite(run_unit: bool, run_agent: bool) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    unit_classes = [
        TestToolDefinitions,
        TestOnboardingTemplate,
        TestDepartmentPolicies,
        TestCreateAdUser,
        TestAssignAdGroups,
        TestProvisionMailbox,
        TestAssignM365License,
        TestDisableAdUser,
        TestRevokeAccess,
        TestGetUserStatus,
        TestToolDispatcher,
        TestOuPlacementRegression,
    ]

    if run_unit:
        for cls in unit_classes:
            suite.addTests(loader.loadTestsFromTestCase(cls))

    if run_agent:
        suite.addTests(loader.loadTestsFromTestCase(TestAgentIntegration))

    return suite


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MOCKCO IT Workflow Orchestrator test suite")
    parser.add_argument("--unit", action="store_true", help="Run unit tests (no API calls)")
    parser.add_argument("--agent", action="store_true", help="Run agent integration tests (requires ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    neither = not args.unit and not args.agent
    run_unit = args.unit or neither
    run_agent = args.agent or neither

    suite = build_suite(run_unit, run_agent)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
