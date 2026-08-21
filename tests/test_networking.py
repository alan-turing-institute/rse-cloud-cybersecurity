"""Tests for infra.networking using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.networking import network_interface, public_ip, virtual_network, vm_subnet


class TestNetworking(unittest.TestCase):
    @pulumi.runtime.test
    def test_virtual_network_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vnet", urn)

        return virtual_network.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_vm_subnet_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vm-subnet", urn)

        return vm_subnet.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_public_ip_is_standard_sku_with_static_allocation(self):
        def check(args: tuple) -> None:
            sku, allocation_method = args
            self.assertEqual(sku["name"], "Standard")
            self.assertEqual(allocation_method, "Static")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            public_ip.sku, public_ip.public_ip_allocation_method
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_network_interface_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vm-nic", urn)

        return network_interface.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]
