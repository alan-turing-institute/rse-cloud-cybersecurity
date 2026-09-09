"""Tests for infra.firewall using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.firewall import firewall, firewall_public_ip, route


class TestFirewall(unittest.TestCase):
    @pulumi.runtime.test
    def test_firewall_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-firewall", urn)

        return firewall.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_firewall_uses_basic_sku(self):
        def check(sku) -> None:
            self.assertEqual(sku["tier"], "Basic")

        return firewall.sku.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_firewall_public_ip_is_standard_sku_with_static_allocation(self):
        def check(args: tuple) -> None:
            sku, allocation_method = args
            self.assertEqual(sku["name"], "Standard")
            self.assertEqual(allocation_method, "Static")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            firewall_public_ip.sku, firewall_public_ip.public_ip_allocation_method
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_nat_rule_forwards_ssh_from_the_documented_source_ip(self):
        def check(nat_rule_collections: list) -> None:
            self.assertEqual(len(nat_rule_collections), 1)
            rule = nat_rule_collections[0]["rules"][0]
            self.assertEqual(rule["source_addresses"], ["193.60.220.253"])
            self.assertEqual(rule["destination_ports"], ["22"])
            self.assertEqual(rule["translated_port"], "22")

        return firewall.nat_rule_collections.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_application_rules_allow_this_vms_cloud_init_dependencies(self):
        def check(application_rule_collections: list) -> None:
            allow_collection = next(
                collection
                for collection in application_rule_collections
                if collection["name"] == "workspaces-allow-restricted"
            )
            fqdns_by_rule_name = {
                rule["name"]: set(rule["target_fqdns"])
                for rule in allow_collection["rules"]
            }
            self.assertTrue(
                {"archive.ubuntu.com", "security.ubuntu.com"}.issubset(
                    fqdns_by_rule_name["AllowUbuntuArchive"]
                )
            )
            self.assertIn(
                "packages.microsoft.com", fqdns_by_rule_name["AllowVsCodeRepo"]
            )
            self.assertIn("dl.google.com", fqdns_by_rule_name["AllowChromeRepo"])
            self.assertIn("*.database.windows.net", fqdns_by_rule_name["AllowAzureSql"])
            self.assertIn(
                "*.blob.core.windows.net", fqdns_by_rule_name["AllowAzureStorage"]
            )
            self.assertEqual(
                fqdns_by_rule_name["AllowAzureCli"],
                {
                    "login.microsoftonline.com",
                    "login.windows.net",
                    "*.login.microsoft.com",
                    "management.azure.com",
                },
            )

        return firewall.application_rule_collections.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_application_rules_deny_snapcraft_upload_and_login(self):
        def check(application_rule_collections: list) -> None:
            deny_collection = next(
                collection
                for collection in application_rule_collections
                if collection["name"] == "workspaces-deny"
            )
            self.assertEqual(deny_collection["action"]["type"], "Deny")
            rule = deny_collection["rules"][0]
            self.assertEqual(
                set(rule["target_fqdns"]),
                {
                    "dashboard.snapcraft.io",
                    "login.ubuntu.com",
                    "upload.apps.ubuntu.com",
                },
            )

        return firewall.application_rule_collections.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_route_sends_all_traffic_via_the_firewall(self):
        def check(args: tuple) -> None:
            address_prefix, next_hop_type = args
            self.assertEqual(address_prefix, "0.0.0.0/0")
            self.assertEqual(next_hop_type, "VirtualAppliance")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            route.address_prefix, route.next_hop_type
        ).apply(check)  # ty: ignore[invalid-argument-type]
