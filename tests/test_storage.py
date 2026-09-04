"""Tests for infra.storage using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.storage import (
    _STORAGE_BLOB_DATA_READER_ROLE_ID,
    blob_container,
    storage_account,
    vm_storage_role_assignment,
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
    def test_vm_storage_role_assignment_is_scoped_to_the_container_read_only(self):
        def check(args: tuple) -> None:
            scope, container_id, principal_type, role_definition_id = args
            # Scoped to the container specifically, not the whole storage
            # account, so every other container is out of the VM's reach
            # (see specs/01-managing-identity.md).
            self.assertEqual(scope, container_id)
            self.assertEqual(principal_type, "ServicePrincipal")
            # Storage Blob Data Reader, not Contributor - read-only.
            self.assertIn(_STORAGE_BLOB_DATA_READER_ROLE_ID, role_definition_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            vm_storage_role_assignment.scope,
            blob_container.id,
            vm_storage_role_assignment.principal_type,
            vm_storage_role_assignment.role_definition_id,
        ).apply(check)  # ty: ignore[invalid-argument-type]
