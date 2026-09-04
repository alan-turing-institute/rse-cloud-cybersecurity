"""Tests for infra.compute using Pulumi's mocking framework."""

import base64
import json
import unittest

import pulumi

from infra.compute import storage_blob_data_reader_role_assignment, virtual_machine


class TestCompute(unittest.TestCase):
    @pulumi.runtime.test
    def test_virtual_machine_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-vm", urn)

        return virtual_machine.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_virtual_machine_has_system_assigned_identity(self):
        def check(identity) -> None:
            self.assertEqual(identity.type, "SystemAssigned")

        return virtual_machine.identity.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

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
    def test_custom_data_mounts_the_storage_container_with_blobfuse2(self):
        def check(os_profile) -> None:
            cloud_init = base64.b64decode(os_profile.custom_data).decode()
            self.assertIn("apt-get install -y fuse3 blobfuse2", cloud_init)
            self.assertIn(
                "systemctl enable --now blobfuse2-rse-demo-container.service",
                cloud_init,
            )

            config_line = next(
                line
                for line in cloud_init.splitlines()
                if "/etc/blobfuse2/rse-demo-container.yaml" in line and "echo" in line
            )
            encoded_config = config_line.split("echo '")[1].split("'")[0]
            blobfuse2_config = base64.b64decode(encoded_config).decode()
            self.assertIn("mode: msi", blobfuse2_config)
            # Blobs can be added outside BlobFuse2 (the retained account key,
            # the Portal) - caching must not mask those external changes.
            self.assertIn("disable-kernel-cache: true", blobfuse2_config)
            self.assertIn("timeout-sec: 0", blobfuse2_config)
            self.assertIn("container: rse-demo-container", blobfuse2_config)
            self.assertIn("type: block", blobfuse2_config)
            # No account key, SAS, or other credential - the managed
            # identity needs none of them.
            self.assertNotIn("account-key", blobfuse2_config)
            self.assertNotIn("sas", blobfuse2_config)

            unit_line = next(
                line
                for line in cloud_init.splitlines()
                if "/etc/systemd/system/blobfuse2-rse-demo-container.service" in line
                and "echo" in line
            )
            encoded_unit = unit_line.split("echo '")[1].split("'")[0]
            blobfuse2_unit = base64.b64decode(encoded_unit).decode()
            self.assertIn("--read-only=true", blobfuse2_unit)
            # Without this, blobfuse2 daemonizes and the ExecStart process
            # exits immediately, so Type=simple sees a clean exit and marks
            # the unit inactive rather than tracking the actual mount.
            self.assertIn("--foreground=true", blobfuse2_unit)
            self.assertIn("Restart=on-failure", blobfuse2_unit)

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
            self.assertEqual(connection["authenticationType"], "SqlLogin")
            self.assertEqual(connection["user"], "sqladmin")
            # The extension only supports entering the password once and
            # remembering it via savePassword - it can't be pre-seeded.
            self.assertEqual(connection["password"], "")
            self.assertTrue(connection["savePassword"])

        return virtual_machine.os_profile.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_storage_role_assignment_grants_read_only_on_the_container_only(self):
        def check(args: tuple) -> None:
            scope, principal_type, role_definition_id = args
            self.assertIn("rse-demo-container", scope)
            self.assertEqual(principal_type, "ServicePrincipal")
            # Storage Blob Data Reader - read-only, not Contributor/Owner.
            self.assertIn("2a2b9908-6ea1-4ae2-8e65-a410df84e7d1", role_definition_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            storage_blob_data_reader_role_assignment.scope,
            storage_blob_data_reader_role_assignment.principal_type,
            storage_blob_data_reader_role_assignment.role_definition_id,
        ).apply(check)  # ty: ignore[invalid-argument-type]
