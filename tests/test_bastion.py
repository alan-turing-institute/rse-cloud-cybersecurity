"""Tests for infra.bastion using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.bastion import bastion_host
from infra.bastion_networking import bastion_public_ip, bastion_subnet


class TestBastion(unittest.TestCase):
    @pulumi.runtime.test
    def test_bastion_host_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-bastion", urn)

        return bastion_host.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_host_uses_standard_sku(self):
        def check(sku) -> None:
            self.assertEqual(sku["name"], "Standard")

        return bastion_host.sku.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_host_enables_tunneling_and_shareable_link(self):
        def check(args: tuple) -> None:
            enable_tunneling, enable_shareable_link = args
            self.assertTrue(enable_tunneling)
            self.assertTrue(enable_shareable_link)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            bastion_host.enable_tunneling, bastion_host.enable_shareable_link
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_bastion_host_uses_the_bastion_subnet_and_public_ip(self):
        def check(args: tuple) -> None:
            ip_configurations, subnet_id, public_ip_id = args
            self.assertEqual(len(ip_configurations), 1)
            configuration = ip_configurations[0]
            self.assertEqual(configuration["subnet"]["id"], subnet_id)
            self.assertEqual(configuration["public_ip_address"]["id"], public_ip_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            bastion_host.ip_configurations, bastion_subnet.id, bastion_public_ip.id
        ).apply(check)  # ty: ignore[invalid-argument-type]
