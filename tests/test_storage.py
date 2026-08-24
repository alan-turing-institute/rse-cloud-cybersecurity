"""Tests for infra.storage using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.storage import blob_container, storage_account


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
