"""Linux virtual machine reachable over RDP with a graphical desktop. The VM
has a system-assigned managed identity (see specs/01-managing-identity.md)
that it uses, via RBAC, to read from the storage account and, via Azure AD
authentication, to read/write the SQL database - no API key or SQL login
password for either path.

VS Code is pre-installed with the storage and mssql extensions, but the
`ms-mssql.mssql` extension has no authentication type that can actually ride
the VM's managed identity (its `mssql.connections[].authenticationType`
schema only supports SqlLogin/Integrated/AzureMFA/
ActiveDirectoryServicePrincipal - confirmed against the extension's own
package.json). The pre-created mssql profile uses AzureMFA, the closest
available option, but that means the operator signing in interactively as
themselves, not the VM's identity. `sqlcmd` (go-sqlcmd) is also installed,
since `sqlcmd --authentication-method ActiveDirectoryManagedIdentity` is the
only path on this VM that genuinely uses the managed identity for database
access (see specs/01-managing-identity.md for the full research).

Uses password authentication rather than an SSH key, in line with delaying
that piece of security hardening to a later iteration.

The Azure Storage extension has no documented settings.json key for
pre-attaching an account, so the operator attaches it once via "Attach
Storage Account..." using Azure AD sign-in (or, for management purposes,
the storage account key handed out as a secret stack output).
"""

import base64
import json
from pathlib import Path

import jinja2
import pulumi
import pulumi_random
from pulumi_azure_native import compute

from infra.database import sql_database, sql_server
from infra.networking import network_interface
from infra.resource_group import resource_group

_MSSQL_PROFILE_NAME = "rse-demo-db"
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_CLOUD_INIT_TEMPLATE_PATH = _TEMPLATES_DIR / "vm-cloud-init.yaml.j2"

config = pulumi.Config()
admin_username = config.get("vm-admin-username") or "azureuser"

vm_admin_password = pulumi_random.RandomPassword(
    "rse-vm-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

_cloud_init_template = jinja2.Template(_CLOUD_INIT_TEMPLATE_PATH.read_text())


def _vscode_settings_json(sql_server_fqdn: str, database_name: str) -> str:
    return json.dumps(
        {
            "mssql.connections": [
                {
                    "profileName": _MSSQL_PROFILE_NAME,
                    "server": sql_server_fqdn,
                    "database": database_name,
                    "authenticationType": "AzureMFA",
                    "encrypt": "Mandatory",
                }
            ]
        }
    )


def _custom_data(sql_server_fqdn: str, database_name: str) -> str:
    vscode_settings_json = _vscode_settings_json(sql_server_fqdn, database_name)
    vscode_settings_b64 = base64.b64encode(vscode_settings_json.encode()).decode()
    cloud_init = _cloud_init_template.render(
        admin_username=admin_username,
        vscode_settings_b64=vscode_settings_b64,
    )
    return base64.b64encode(cloud_init.encode()).decode()


custom_data = pulumi.Output.all(  # ty: ignore[missing-argument]
    sql_server.fully_qualified_domain_name, sql_database.name
).apply(lambda args: _custom_data(*args))  # ty: ignore[invalid-argument-type]

virtual_machine = compute.VirtualMachine(
    "rse-vm",
    resource_group_name=resource_group.name,
    identity=compute.VirtualMachineIdentityArgs(
        type=compute.ResourceIdentityType.SYSTEM_ASSIGNED
    ),
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
        computer_name="rse-vm",
        admin_username=admin_username,
        admin_password=vm_admin_password.result,
        custom_data=custom_data,
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
