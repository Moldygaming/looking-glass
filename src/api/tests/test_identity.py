import unittest

from app.identity import evaluate_sso, group_ids_match, role_match


class EvaluateSsoTests(unittest.TestCase):
    def test_disabled_is_denied(self):
        allowed, reason = evaluate_sso(
            disabled=True,
            in_admin_group=True,
            has_admin_app_role=True,
            in_access_group=True,
            access_group_configured=True,
            has_portal_access=True,
        )
        self.assertFalse(allowed)
        self.assertIn("disabled", reason.lower())

    def test_admin_group_is_admin(self):
        allowed, reason = evaluate_sso(
            disabled=False,
            in_admin_group=True,
            has_admin_app_role=False,
            in_access_group=False,
            access_group_configured=False,
            has_portal_access=False,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "admin")

    def test_app_role_is_admin(self):
        allowed, reason = evaluate_sso(
            disabled=False,
            in_admin_group=False,
            has_admin_app_role=True,
            in_access_group=False,
            access_group_configured=False,
            has_portal_access=False,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "admin")

    def test_portal_role_allows_sign_in(self):
        allowed, reason = evaluate_sso(
            disabled=False,
            in_admin_group=False,
            has_admin_app_role=False,
            in_access_group=False,
            access_group_configured=False,
            has_portal_access=True,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "portal")

    def test_unknown_entra_user_is_denied(self):
        allowed, reason = evaluate_sso(
            disabled=False,
            in_admin_group=False,
            has_admin_app_role=False,
            in_access_group=False,
            access_group_configured=False,
            has_portal_access=False,
        )
        self.assertFalse(allowed)
        self.assertIn("admin group", reason.lower())

    def test_optional_access_group(self):
        allowed, reason = evaluate_sso(
            disabled=False,
            in_admin_group=False,
            has_admin_app_role=False,
            in_access_group=True,
            access_group_configured=True,
            has_portal_access=False,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "access_group")

    def test_access_group_configured_but_not_member(self):
        allowed, reason = evaluate_sso(
            disabled=False,
            in_admin_group=False,
            has_admin_app_role=False,
            in_access_group=False,
            access_group_configured=True,
            has_portal_access=False,
        )
        self.assertFalse(allowed)
        self.assertIn("access group", reason.lower())


class ClaimMatchTests(unittest.TestCase):
    def test_group_ids_case_insensitive(self):
        self.assertTrue(group_ids_match("ABC-def", ["abc-DEF"]))
        self.assertFalse(group_ids_match("", ["abc"]))
        self.assertFalse(group_ids_match("abc", []))

    def test_role_match(self):
        self.assertTrue(role_match("PlatformAdmin", ["platformadmin"]))
        self.assertFalse(role_match("PlatformAdmin", ["User"]))


if __name__ == "__main__":
    unittest.main()
