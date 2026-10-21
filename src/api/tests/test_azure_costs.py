import unittest
from datetime import date

from app.connectors.base import NormalizedCost
from app.services.azure_resources import (
    costs_from_details_csv,
    friendly_resource_type,
    month_windows,
    parse_arm_resource,
    parse_usage_date,
    reconcile_unallocated,
)


CSV = """\
Date,ResourceId,ResourceGroup,SubscriptionId,SubscriptionName,MeterCategory,MeterName,ResourceLocation,CostInBillingCurrency,BillingCurrency,Quantity,UnitOfMeasure,Tags,ConsumedService
2026-10-01,/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app1,rg,sub,Dev,Azure App Service,F1,uksouth,1.50,GBP,24,Hours,"{}",Microsoft.Web
2026-10-01,/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1,rg,sub,Dev,Virtual Machines,D2s v3,uksouth,12.00,GBP,24,Hours,"{""team"":""infra""}",Microsoft.Compute
2026-10-01,/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/st1,rg,sub,Dev,Storage,Hot LRS,uksouth,0.40,GBP,10,GB,"{}",Microsoft.Storage
2026-10-01,/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Sql/servers/sql1/databases/db1,rg,sub,Dev,SQL Database,S0,uksouth,4.00,GBP,1,Hours,"{}",Microsoft.Sql
2026-10-01,,rg,sub,Dev,Bandwidth,Data Transfer Out,uksouth,0.20,GBP,1,GB,"{}",Microsoft.Network
"""


class ArmParseTests(unittest.TestCase):
    def test_web_app_vm_and_nested_database(self):
        name, rtype, sub, rg = parse_arm_resource(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app1"
        )
        self.assertEqual((name, rtype, sub, rg), ("app1", "Microsoft.Web/sites", "sub", "rg"))

        name, rtype, _, _ = parse_arm_resource(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        )
        self.assertEqual((name, rtype), ("vm1", "Microsoft.Compute/virtualMachines"))

        name, rtype, _, _ = parse_arm_resource(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Sql/servers/sql1/databases/db1"
        )
        self.assertEqual((name, rtype), ("db1", "Microsoft.Sql/servers/databases"))

    def test_friendly_names_cover_more_than_web_apps(self):
        self.assertEqual(friendly_resource_type("Microsoft.Web/sites"), "App Service")
        self.assertEqual(friendly_resource_type("Microsoft.Web/serverfarms"), "App Service plan")
        self.assertEqual(friendly_resource_type("Microsoft.Compute/virtualMachines"), "Virtual Machine")
        self.assertEqual(friendly_resource_type("Microsoft.Compute/disks"), "Managed Disk")
        self.assertEqual(friendly_resource_type("Microsoft.Network/publicIPAddresses"), "Public IP")
        self.assertEqual(friendly_resource_type("Virtual Machine"), "Virtual Machine")
        self.assertEqual(friendly_resource_type("Microsoft.Compute/availabilitySets"), "Availability Sets")


class CostDetailsTests(unittest.TestCase):
    def test_csv_keeps_every_resource_type(self):
        rows = costs_from_details_csv(CSV, "/subscriptions/sub", {"env": "dev"}, "GBP")
        types = {row.resource_type for row in rows}
        self.assertEqual(
            types,
            {"App Service", "Virtual Machine", "Storage account", "SQL database", "Unallocated"},
        )
        vm = next(row for row in rows if row.resource_name == "vm1")
        self.assertEqual(vm.category, "Compute")
        self.assertEqual(vm.tags, {"env": "dev", "team": "infra"})
        bandwidth = next(row for row in rows if row.resource_type == "Unallocated")
        self.assertEqual(bandwidth.service, "Bandwidth")
        self.assertEqual(bandwidth.category, "Network")
        self.assertAlmostEqual(sum(row.cost for row in rows), 18.1)

    def test_usage_date_accepts_cost_details_formats(self):
        self.assertEqual(parse_usage_date("10/01/2026", date(2026, 1, 1)), date(2026, 10, 1))
        self.assertEqual(parse_usage_date("20261001", date(2026, 1, 1)), date(2026, 10, 1))
        self.assertEqual(parse_usage_date("2026-10-01", date(2026, 1, 1)), date(2026, 10, 1))

    def test_month_windows_stay_inside_a_calendar_month(self):
        windows = month_windows(date(2026, 1, 15), date(2026, 3, 2))
        self.assertEqual(
            windows,
            [
                (date(2026, 1, 15), date(2026, 1, 31)),
                (date(2026, 2, 1), date(2026, 2, 28)),
                (date(2026, 3, 1), date(2026, 3, 2)),
            ],
        )


class ReconcileTests(unittest.TestCase):
    def test_gap_becomes_an_unallocated_row(self):
        day = date(2026, 10, 1)
        web = _row(day, "app1", "App Service", "Azure App Service", 10)
        services = [_row(day, "Azure App Service", "Azure App Service", "Azure App Service", 10), _row(day, "Bandwidth", "Bandwidth", "Bandwidth", 2)]
        rows = reconcile_unallocated([web], services, "/subscriptions/sub")
        self.assertEqual(len(rows), 2)
        extra = rows[1]
        self.assertEqual(extra.resource_type, "Unallocated")
        self.assertAlmostEqual(extra.cost, 2)

    def test_matching_totals_add_nothing(self):
        day = date(2026, 10, 1)
        web = _row(day, "app1", "App Service", "Azure App Service", 10)
        service = _row(day, "Azure App Service", "Azure App Service", "Azure App Service", 10)
        rows = reconcile_unallocated([web], [service], "/subscriptions/sub")
        self.assertEqual(rows, [web])


def _row(day: date, name: str, resource_type: str, service: str, cost: float) -> NormalizedCost:
    return NormalizedCost(
        usage_date=day,
        account_id="sub",
        account_name="Dev",
        resource_id=f"/subscriptions/sub/{name}",
        resource_name=name,
        resource_type=resource_type,
        service=service,
        category="Other",
        meter=service,
        region="uksouth",
        cost=cost,
        amortized_cost=cost,
        currency="GBP",
    )


if __name__ == "__main__":
    unittest.main()
