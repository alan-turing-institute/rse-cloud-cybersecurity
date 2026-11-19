"""Linux virtual machine reachable over RDP with a graphical desktop, and VS
Code pre-installed as the *only* way to reach the storage account and the
SQL database (see specs/01-the-scenario.md - no Azure CLI/sqlcmd fallback,
no managed identity/RBAC yet).

Uses password authentication rather than an SSH key, in line with delaying
security hardening to a later iteration.

The mssql connection profile is pre-created (server/database/username), but
- per the extension's own documented behaviour - the password isn't
something that can be pre-seeded into settings.json; it's entered once on
first connect and then remembered via VS Code's secret storage
(savePassword=true). Likewise the Azure Storage extension has no documented
settings.json key for pre-attaching an account, so the operator attaches it
once via "Attach Storage Account..." using the connection string handed out
as a secret stack output.
"""

import base64
import json
from pathlib import Path

import jinja2
import pulumi
import pulumi_random
from pulumi_azure_native import compute

from infra.networking import network_interface
from infra.resource_group import resource_group

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_CLOUD_INIT_TEMPLATE_PATH = _TEMPLATES_DIR / "vm-cloud-init.yaml.j2"

config = pulumi.Config()
vm_admin_username = config.get("vm-admin-username") or "azureuser"

vm_admin_password = pulumi_random.RandomPassword(
    "app-vm-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

_cloud_init_template = jinja2.Template(_CLOUD_INIT_TEMPLATE_PATH.read_text())

def custom_data() -> str:
    cloud_init = _cloud_init_template.render(vm_admin_username=vm_admin_username)
    return base64.b64encode(cloud_init.encode()).decode()

virtual_machine = compute.VirtualMachine(
    "app-vm",
    resource_group_name=resource_group.name,
    hardware_profile=compute.HardwareProfileArgs(vm_size="Standard_B2s"),
    network_profile=compute.NetworkProfileArgs(
        network_interfaces=[
            compute.NetworkInterfaceReferenceArgs(id=network_interface.id, primary=True)
        ],
    ),
    storage_profile=compute.StorageProfileArgs(
        image_reference=compute.ImageReferenceArgs(
            publisher="Canonical",
            offer="0001-com-ubuntu-server-jammy",
            sku="22_04-lts-gen2",
            version="latest",
        ),
        os_disk=compute.OSDiskArgs(
            create_option=compute.DiskCreateOptionTypes.FROM_IMAGE,
            managed_disk=compute.ManagedDiskParametersArgs(
                storage_account_type=compute.StorageAccountTypes.STANDARD_LRS,
            ),
        ),
    ),
    os_profile=compute.OSProfileArgs(
        computer_name="app-vm",
        admin_username=vm_admin_username,
        admin_password=vm_admin_password.result,
        custom_data=custom_data(),
        linux_configuration=compute.LinuxConfigurationArgs(
            disable_password_authentication=False,
        ),
    ),
    opts=pulumi.ResourceOptions(
        # Azure ignores osProfile.customData on VM updates, so without this the
        # cloud-init change would silently not take effect; force a
        # delete-and-recreate instead.
        replace_on_changes=["osProfile.customData"],
        delete_before_replace=True,
    ),
)
