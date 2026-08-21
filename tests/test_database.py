"""Tests for infra.database using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.database import postgres_database, postgres_firewall_rule, postgres_server


class TestDatabase(unittest.TestCase):
    @pulumi.runtime.test
    def test_postgres_server_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-postgres-server", urn)

        return postgres_server.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_postgres_server_uses_burstable_sku_and_password_auth(self):
        def check(args: tuple) -> None:
            sku, auth_config = args
            self.assertEqual(sku["tier"], "Burstable")
            self.assertEqual(sku["name"], "Standard_B1ms")
            self.assertEqual(auth_config["password_auth"], "Enabled")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            postgres_server.sku, postgres_server.auth_config
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_postgres_server_is_not_vnet_integrated(self):
        def check(network) -> None:
            self.assertIsNone(network.delegated_subnet_resource_id)
            self.assertEqual(network.public_network_access, "Enabled")

        return postgres_server.network.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_firewall_rule_opens_the_full_public_range(self):
        def check(args: tuple) -> None:
            start_ip, end_ip = args
            self.assertEqual(start_ip, "0.0.0.0")
            self.assertEqual(end_ip, "255.255.255.255")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            postgres_firewall_rule.start_ip_address,
            postgres_firewall_rule.end_ip_address,
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_database_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse_demo_db", urn)

        return postgres_database.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]
