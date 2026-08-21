"""Tests for infra.compute using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.compute import virtual_machine


class TestCompute(unittest.TestCase):
    @pulumi.runtime.test
    def test_virtual_machine_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vm", urn)

        return virtual_machine.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_virtual_machine_uses_cheapest_size(self):
        def check(hardware_profile) -> None:
            self.assertEqual(hardware_profile.vm_size, "Standard_B1s")

        return virtual_machine.hardware_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_virtual_machine_uses_linux_image(self):
        def check(storage_profile) -> None:
            self.assertEqual(storage_profile.image_reference.publisher, "Canonical")

        return virtual_machine.storage_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_virtual_machine_has_no_managed_identity(self):
        def check(identity) -> None:
            self.assertIsNone(identity)

        return virtual_machine.identity.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_virtual_machine_uses_password_auth(self):
        def check(os_profile) -> None:
            self.assertFalse(
                os_profile.linux_configuration.disable_password_authentication
            )
            self.assertIsNotNone(os_profile.admin_password)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )
