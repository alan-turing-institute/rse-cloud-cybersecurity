"""Tests for infra.database using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.database import sql_database, sql_firewall_rule, sql_server


class TestDatabase(unittest.TestCase):
    @pulumi.runtime.test
    def test_sql_server_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-sql-server", urn)

        return sql_server.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_sql_database_uses_basic_tier(self):
        def check(sku) -> None:
            self.assertEqual(sku["tier"], "Basic")
            self.assertEqual(sku["name"], "Basic")

        return sql_database.sku.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_firewall_rule_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-sql-allow-all", urn)

        return sql_firewall_rule.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_database_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse_demo_db", urn)

        return sql_database.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]
