"""Tests for infra.compute using Pulumi's mocking framework."""

import base64
import json
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
    def test_virtual_machine_has_a_system_assigned_managed_identity(self):
        def check(identity) -> None:
            self.assertEqual(identity.type, "SystemAssigned")

        return virtual_machine.identity.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_virtual_machine_uses_cheapest_size_that_fits_the_desktop_and_vscode(self):
        def check(hardware_profile) -> None:
            self.assertEqual(hardware_profile.vm_size, "Standard_B2s")

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
    def test_virtual_machine_uses_password_auth(self):
        def check(os_profile) -> None:
            self.assertFalse(
                os_profile.linux_configuration.disable_password_authentication
            )
            self.assertIsNotNone(os_profile.admin_password)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_custom_data_provisions_the_graphical_desktop_and_rdp(self):
        def check(os_profile) -> None:
            cloud_init = base64.b64decode(os_profile.custom_data).decode()
            self.assertIn("xfce4", cloud_init)
            self.assertIn("xrdp", cloud_init)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_custom_data_installs_vscode_and_its_extensions(self):
        def check(os_profile) -> None:
            cloud_init = base64.b64decode(os_profile.custom_data).decode()
            self.assertIn("apt-get install -y code", cloud_init)
            self.assertIn("ms-mssql.mssql", cloud_init)
            self.assertIn("ms-azuretools.vscode-azurestorage", cloud_init)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_custom_data_installs_chrome_and_sets_it_as_default_browser(self):
        def check(os_profile) -> None:
            cloud_init = base64.b64decode(os_profile.custom_data).decode()
            self.assertIn("apt-get install -y google-chrome-stable", cloud_init)
            self.assertIn(
                "update-alternatives --set x-www-browser /usr/bin/google-chrome-stable",
                cloud_init,
            )
            self.assertIn("text/html=google-chrome.desktop", cloud_init)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_custom_data_pre_creates_the_mssql_connection_profile(self):
        def check(os_profile) -> None:
            cloud_init = base64.b64decode(os_profile.custom_data).decode()
            settings_line = next(
                line for line in cloud_init.splitlines() if "settings.json" in line
            )
            encoded_settings = settings_line.split("echo '")[1].split("'")[0]
            settings = json.loads(base64.b64decode(encoded_settings))
            connections = settings["mssql.connections"]
            self.assertEqual(len(connections), 1)
            connection = connections[0]
            # AzureMFA is the closest auth type the extension's schema
            # actually supports for Azure AD sign-in - there's no
            # managed-identity-flavored option to pre-seed instead (see
            # specs/01-managing-identity.md). No SQL login/password to
            # pre-seed or blank out any more, either.
            self.assertEqual(connection["authenticationType"], "AzureMFA")
            self.assertNotIn("user", connection)
            self.assertNotIn("password", connection)
            self.assertNotIn("savePassword", connection)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_custom_data_installs_sqlcmd_as_the_managed_identity_db_fallback(self):
        def check(os_profile) -> None:
            cloud_init = base64.b64decode(os_profile.custom_data).decode()
            self.assertIn("apt-get install -y sqlcmd", cloud_init)

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )
