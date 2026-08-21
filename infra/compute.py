"""Linux virtual machine that can reach the storage account and the SQL
database over the public internet (see specs/01-the-scenario.md - no managed
identity/RBAC yet, storage access uses the account key/connection string
exported as a secret stack output instead).

Uses password authentication rather than an SSH key, in line with delaying
security hardening to a later iteration.
"""

import base64

import pulumi
import pulumi_random
from pulumi_azure_native import compute

from infra.networking import network_interface
from infra.resource_group import resource_group

config = pulumi.Config()
admin_username = config.get("vm-admin-username") or "azureuser"

vm_admin_password = pulumi_random.RandomPassword(
    "rse-vm-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

cloud_init = """#cloud-config
package_update: true
packages:
  - azure-cli
  - unixodbc-dev
runcmd:
  - curl -sSL -O https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb
  - dpkg -i packages-microsoft-prod.deb
  - rm -f packages-microsoft-prod.deb
  - apt-get update
  - ACCEPT_EULA=Y apt-get install -y mssql-tools18
  - echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> /etc/profile.d/mssql-tools.sh
"""

virtual_machine = compute.VirtualMachine(
    "rse-vm",
    resource_group_name=resource_group.name,
    hardware_profile=compute.HardwareProfileArgs(vm_size="Standard_B1s"),
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
        custom_data=base64.b64encode(cloud_init.encode()).decode(),
        linux_configuration=compute.LinuxConfigurationArgs(
            disable_password_authentication=False,
        ),
    ),
)
