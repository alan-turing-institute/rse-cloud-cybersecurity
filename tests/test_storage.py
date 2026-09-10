"""Tests for infra.storage using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.dns import dns_id
from infra.firewall import firewall_management_subnet
from infra.networking import vm_subnet
from infra.storage import (
    blob_container,
    storage_account,
    storage_account_private_dns_zone_group,
    storage_account_private_endpoint,
    storage_subnet,
)


class TestStorage(unittest.TestCase):
    @pulumi.runtime.test
    def test_storage_account_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-storage-account", urn)

        return storage_account.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_storage_account_uses_cheapest_sku_and_kind(self):
        def check(args: tuple) -> None:
            kind, sku = args
            self.assertEqual(kind, "StorageV2")
            self.assertEqual(sku["name"], "Standard_LRS")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            storage_account.kind, storage_account.sku
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_blob_container_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-demo-container", urn)

        return blob_container.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_storage_subnet_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-storage-subnet", urn)

        return storage_subnet.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_storage_subnet_has_the_microsoft_storage_service_endpoint(self):
        def check(service_endpoints: list) -> None:
            self.assertEqual(len(service_endpoints), 1)
            self.assertEqual(service_endpoints[0]["service"], "Microsoft.Storage")

        return storage_subnet.service_endpoints.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_storage_subnet_does_not_overlap_the_firewall_management_subnet(self):
        def check(args: tuple) -> None:
            storage_prefix, firewall_management_prefix = args
            self.assertNotEqual(storage_prefix, firewall_management_prefix)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            storage_subnet.address_prefix, firewall_management_subnet.address_prefix
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_storage_account_denies_by_default_with_azure_services_bypass(self):
        def check(network_rule_set) -> None:
            self.assertEqual(network_rule_set["default_action"], "Deny")
            self.assertEqual(network_rule_set["bypass"], "AzureServices")

        return storage_account.network_rule_set.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_storage_account_ip_rules_allow_only_the_turing_vpn(self):
        def check(network_rule_set) -> None:
            addresses = {
                rule["i_p_address_or_range"] for rule in network_rule_set["ip_rules"]
            }
            self.assertEqual(addresses, {"193.60.220.253"})

        return storage_account.network_rule_set.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_storage_account_virtual_network_rules_include_storage_subnet_and_vm_subnet(
        self,
    ):
        def check(args: tuple) -> None:
            network_rule_set, storage_subnet_id, vm_subnet_id = args
            vnet_rule_ids = {
                rule["virtual_network_resource_id"]
                for rule in network_rule_set["virtual_network_rules"]
            }
            self.assertIn(storage_subnet_id, vnet_rule_ids)
            self.assertIn(vm_subnet_id, vnet_rule_ids)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            storage_account.network_rule_set, storage_subnet.id, vm_subnet.id
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_storage_account_encrypts_blob_and_file_at_rest(self):
        def check(encryption) -> None:
            services = encryption["services"]
            self.assertTrue(services["blob"]["enabled"])
            self.assertTrue(services["file"]["enabled"])

        return storage_account.encryption.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_storage_account_private_endpoint_targets_blob(self):
        def check(connections: list) -> None:
            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].group_ids, ["blob"])

        return storage_account_private_endpoint.private_link_service_connections.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_storage_account_private_endpoint_uses_the_storage_subnet(self):
        def check(args: tuple) -> None:
            endpoint_subnet_id, subnet_id = args
            self.assertEqual(endpoint_subnet_id, subnet_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            storage_account_private_endpoint.subnet.id, storage_subnet.id
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_storage_account_private_dns_zone_group_populates_the_blob_zone(self):
        def check(args: tuple) -> None:
            configs, blob_zone_id = args
            self.assertEqual(len(configs), 1)
            self.assertEqual(configs[0]["private_dns_zone_id"], blob_zone_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            storage_account_private_dns_zone_group.private_dns_zone_configs,
            dns_id["blob"],
        ).apply(check)  # ty: ignore[invalid-argument-type]
