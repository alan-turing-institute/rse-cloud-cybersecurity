"""Tests for infra.networking using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.networking import (
    network_interface,
    network_security_group,
    virtual_network,
    vm_subnet,
)


class TestNetworking(unittest.TestCase):
    @pulumi.runtime.test
    def test_virtual_network_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vnet", urn)

        return virtual_network.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_network_security_group_allows_inbound_ssh_and_rdp_from_internet(self):
        def check(security_rules: list) -> None:
            self.assertEqual(len(security_rules), 2)
            rules_by_port = {
                rule.destination_port_range: rule for rule in security_rules
            }
            self.assertEqual(set(rules_by_port), {"22", "3389"})
            for rule in rules_by_port.values():
                self.assertEqual(rule.direction, "Inbound")
                self.assertEqual(rule.access, "Allow")
                self.assertEqual(rule.protocol, "Tcp")
                self.assertEqual(rule.source_address_prefix, "Internet")

        return network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_vm_subnet_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vm-subnet", urn)

        return vm_subnet.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_vm_subnet_uses_the_network_security_group(self):
        def check(args: tuple) -> None:
            subnet_nsg_id, nsg_id = args
            self.assertEqual(subnet_nsg_id, nsg_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            vm_subnet.network_security_group.id, network_security_group.id
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_vm_has_no_public_ip(self):
        def check(ip_configurations: list) -> None:
            for ip_configuration in ip_configurations:
                for configuration in ip_configuration:
                    if configuration["name"] == "rse-vm-ip-config":
                        self.assertEqual(
                            configuration.get("public_ip_address", None), None
                        )

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            network_interface.ip_configurations
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_network_interface_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vm-nic", urn)

        return network_interface.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]
