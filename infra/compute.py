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
from pulumi import ResourceOptions
from pulumi_azure_native import compute, monitor

from infra.database import admin_username as db_admin_username
from infra.database import sql_database, sql_server
from infra.monitoring import data_collection_endpoint, data_collection_rule_vms
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
                    "authenticationType": "SqlLogin",
                    "user": db_admin_username,
                    "password": "",
                    "savePassword": True,
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
    diagnostics_profile=compute.DiagnosticsProfileArgs(
        boot_diagnostics=compute.BootDiagnosticsArgs(enabled=True)
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
    vm_name="rse-vm-workspace-vm",
    identity=compute.VirtualMachineIdentityArgs(
        type=compute.ResourceIdentityType.SYSTEM_ASSIGNED,
    ),
    opts=pulumi.ResourceOptions(
        # Azure ignores osProfile.customData on VM updates, so without this the
        # cloud-init change would silently not take effect; force a
        # delete-and-recreate instead.
        replace_on_changes=["osProfile.customData"],
        delete_before_replace=True,
    ),
)

# Register with Log Analytics workspace
compute.VirtualMachineExtension(
    "rse-azure-monitor-extension",
    auto_upgrade_minor_version=True,
    enable_automatic_upgrade=True,
    publisher="Microsoft.Azure.Monitor",
    resource_group_name=resource_group.name,
    type="AzureMonitorLinuxAgent",
    type_handler_version="1.0",
    vm_extension_name="AzureMonitorLinuxAgent",
    vm_name=virtual_machine.name,
    opts=ResourceOptions(parent=virtual_machine),
)

# Register with data collection rule
monitor.DataCollectionRuleAssociation(
    "rse-dcra-to-dcr",
    association_name="rse-dcr-vms-association",  # this name is required
    data_collection_rule_id=data_collection_rule_vms.id,
    resource_uri=virtual_machine.id,
    opts=ResourceOptions(parent=virtual_machine),
)

# Register with data collection endpoint
monitor.DataCollectionRuleAssociation(
    "rse-dcra-to-dce",
    association_name="configurationAccessEndpoint",  # this name is required
    data_collection_endpoint_id=data_collection_endpoint.id,
    resource_uri=virtual_machine.id,
    opts=ResourceOptions(parent=virtual_machine),
)
