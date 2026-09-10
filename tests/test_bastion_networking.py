"""Tests for infra.bastion_networking using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.bastion_networking import (
    bastion_network_security_group,
    bastion_public_ip,
    bastion_subnet,
)
from infra.networking import vm_subnet


class TestBastionNetworking(unittest.TestCase):
    @pulumi.runtime.test
    def test_bastion_subnet_is_named_azurebastionsubnet(self):
        def check_urn(urn: str) -> None:
            self.assertIn("AzureBastionSubnet", urn)

        return bastion_subnet.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_subnet_uses_a_distinct_address_space_from_the_vm_subnet(self):
        def check(args: tuple) -> None:
            bastion_prefix, vm_prefix = args
            self.assertNotEqual(bastion_prefix, vm_prefix)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            bastion_subnet.address_prefix, vm_subnet.address_prefix
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_subnet_uses_the_bastion_network_security_group(self):
        def check(args: tuple) -> None:
            subnet_nsg_id, nsg_id = args
            self.assertEqual(subnet_nsg_id, nsg_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            bastion_subnet.network_security_group.id,
            bastion_network_security_group.id,
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_public_ip_is_standard_sku_with_static_allocation(self):
        def check(args: tuple) -> None:
            sku, allocation_method = args
            self.assertEqual(sku["name"], "Standard")
            self.assertEqual(allocation_method, "Static")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            bastion_public_ip.sku, bastion_public_ip.public_ip_allocation_method
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_nsg_allows_https_inbound_from_internet(self):
        def check(security_rules: list) -> None:
            rules_by_name = {rule.name: rule for rule in security_rules}
            rule = rules_by_name["allow-http-inbound"]
            self.assertEqual(rule.direction, "Inbound")
            self.assertEqual(rule.access, "Allow")
            self.assertEqual(rule.destination_port_range, "443")
            self.assertEqual(rule.source_address_prefix, "Internet")

        return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_nsg_allows_control_plane_management_traffic(self):
        def check(security_rules: list) -> None:
            rules_by_name = {rule.name: rule for rule in security_rules}
            rule = rules_by_name["allow-gateway-manager-inbound"]
            self.assertEqual(rule.direction, "Inbound")
            self.assertEqual(rule.access, "Allow")
            self.assertEqual(rule.destination_port_range, "443")
            self.assertEqual(rule.source_address_prefix, "GatewayManager")

        return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_nsg_allows_outbound_ssh_and_rdp_to_the_target_subnet(self):
        def check(security_rules: list) -> None:
            rules_by_name = {rule.name: rule for rule in security_rules}
            for name, port in (
                ("allow-ssh-outbound", "22"),
                ("allow-rdp-outbound", "3389"),
            ):
                rule = rules_by_name[name]
                self.assertEqual(rule.direction, "Outbound")
                self.assertEqual(rule.access, "Allow")
                self.assertEqual(rule.destination_port_range, port)
                self.assertEqual(rule.destination_address_prefix, "VirtualNetwork")

        return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_nsg_has_all_eleven_mandatory_rules(self):
        # Microsoft documents this rule set as mandatory - Bastion deployment
        # fails if any of them is missing. See README-Bastion.md's references.
        def check(security_rules: list) -> None:
            self.assertEqual(len(security_rules), 11)

        return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]
