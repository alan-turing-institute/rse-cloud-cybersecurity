"""Tests for infra.database using Pulumi's mocking framework."""

import os
import unittest

import pulumi

from infra.database import (
    sql_database,
    sql_firewall_rule,
    sql_server,
    sql_server_aad_administrator,
)


class TestDatabase(unittest.TestCase):
    @pulumi.runtime.test
    def test_sql_server_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-sql-server", urn)

        return sql_server.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_sql_server_aad_administrator_uses_the_env_supplied_principal(self):
        def check(args: tuple) -> None:
            login, sid, administrator_type = args
            # Set by tests/conftest.py before infra is imported, since
            # infra.database reads these from the environment at module
            # scope (see specs/01-managing-identity.md).
            self.assertEqual(login, os.environ["AAD_ADMIN_LOGIN"])
            self.assertEqual(sid, os.environ["AAD_ADMIN_OBJECT_ID"])
            self.assertEqual(administrator_type, "ActiveDirectory")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            sql_server_aad_administrator.login,
            sql_server_aad_administrator.sid,
            sql_server_aad_administrator.administrator_type,
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_sql_database_uses_basic_tier(self):
        def check(sku) -> None:
            self.assertEqual(sku["tier"], "Basic")
            self.assertEqual(sku["name"], "Basic")

        return sql_database.sku.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_sql_server_still_has_the_admin_login_kept_for_management(self):
        def check(administrator_login: str) -> None:
            # The VM no longer depends on this, but it's kept exported for
            # a human to manage the server directly (see
            # specs/01-managing-identity.md).
            self.assertEqual(administrator_login, "sqladmin")

        return sql_server.administrator_login.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

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
