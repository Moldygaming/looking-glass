import unittest

from app.entra.audit import redact
from app.entra.bulk import parse_bulk_csv, validate_usage_location
from app.entra.skus import assigned_from_graph, friendly_sku_name


class BulkCsvTests(unittest.TestCase):
    def test_parses_actions_and_lists(self):
        rows = parse_bulk_csv(
            "action,user_principal_name,display_name,groups,licenses\n"
            "create,ada@contoso.com,Ada Lovelace,Finance;Helpdesk,SPE_E5|POWER_BI_PRO\n"
            "\n"
            "disable,old@contoso.com,,,\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].action, "create")
        self.assertEqual(rows[0].groups, ["Finance", "Helpdesk"])
        self.assertEqual(rows[0].licenses, ["SPE_E5", "POWER_BI_PRO"])
        self.assertEqual(rows[1].line, 3)
        self.assertEqual(rows[1].action, "disable")

    def test_rejects_missing_header(self):
        with self.assertRaises(ValueError):
            parse_bulk_csv("display_name\nAda\n")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_bulk_csv("   ")

    def test_usage_location(self):
        self.assertEqual(validate_usage_location("gb"), "GB")
        self.assertEqual(validate_usage_location(""), "")
        with self.assertRaises(ValueError):
            validate_usage_location("United Kingdom")


class LicenseShapeTests(unittest.TestCase):
    def test_graph_and_stored_shapes(self):
        raw = assigned_from_graph(
            [{"skuId": "sku-1", "disabledPlans": ["plan"]}],
            {"sku-1": "SPE_E5"},
        )
        self.assertEqual(raw[0]["sku_part_number"], "SPE_E5")
        again = assigned_from_graph(raw)
        self.assertEqual(again[0]["sku_id"], "sku-1")
        self.assertEqual(again[0]["disabled_plans"], ["plan"])

    def test_friendly_name(self):
        self.assertEqual(friendly_sku_name("SPE_E5"), "Microsoft 365 E5")
        self.assertEqual(friendly_sku_name("CUSTOM_SKU"), "CUSTOM SKU")


class AuditRedactTests(unittest.TestCase):
    def test_password_is_not_stored(self):
        cleaned = redact({"display_name": "Ada", "password": "secret", "nested": {"client_secret": "x"}})
        self.assertEqual(cleaned["display_name"], "Ada")
        self.assertEqual(cleaned["password"], "***")
        self.assertEqual(cleaned["nested"]["client_secret"], "***")


if __name__ == "__main__":
    unittest.main()
