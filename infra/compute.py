"""Linux virtual machine reachable over RDP with a graphical desktop.

The VM's system-assigned managed identity (`identity=` below) is granted
read-only access to rse-demo-container only (see
`storage_blob_data_reader_role_assignment` below, and
specs/02-managing-identity-storage.md) - it's mounted directly on the VM's
filesystem via BlobFuse2 (`mode: msi`), so no sign-in step is needed to
browse it. The Azure CLI is also installed (see below); with this identity's
read-only grant, `az storage blob download --auth-mode login` works but
`az storage blob upload` does not - see README-Storage.md.

Uses password authentication rather than an SSH key, in line with delaying
security hardening to a later iteration.
"""

import base64
from pathlib import Path

import jinja2
import pulumi
import pulumi_random
from pulumi import ResourceOptions
from pulumi_azure_native import authorization, compute, monitor

from infra.monitoring import data_collection_endpoint, data_collection_rule_vms
from infra.networking import network_interface
from infra.resource_group import resource_group
from infra.storage import blob_container, storage_account

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_CLOUD_INIT_TEMPLATE_PATH = _TEMPLATES_DIR / "vm-cloud-init.yaml.j2"
_BLOBFUSE2_CONFIG_TEMPLATE_PATH = _TEMPLATES_DIR / "blobfuse2-config.yaml.j2"
_BLOBFUSE2_UNIT_TEMPLATE_PATH = _TEMPLATES_DIR / "blobfuse2.service.j2"

_BLOBFUSE2_MOUNT_PATH = "/mnt/rse-demo-container"
_BLOBFUSE2_CONFIG_PATH = "/etc/blobfuse2/rse-demo-container.yaml"
_BLOBFUSE2_SERVICE_NAME = "blobfuse2-rse-demo-container.service"

# Storage Blob Data Reader - a fixed, well-known built-in role GUID, same
# across all Azure tenants.
_STORAGE_BLOB_DATA_READER_ROLE_GUID = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"

config = pulumi.Config()
admin_username = config.get("vm-admin-username") or "azureuser"

vm_admin_password = pulumi_random.RandomPassword(
    "rse-vm-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

_cloud_init_template = jinja2.Template(_CLOUD_INIT_TEMPLATE_PATH.read_text())
_blobfuse2_config_template = jinja2.Template(
    _BLOBFUSE2_CONFIG_TEMPLATE_PATH.read_text()
)
_blobfuse2_unit_template = jinja2.Template(_BLOBFUSE2_UNIT_TEMPLATE_PATH.read_text())


def _custom_data(storage_account_name: str) -> str:
    blobfuse2_config_yaml = _blobfuse2_config_template.render(
        storage_account_name=storage_account_name
    )
    blobfuse2_config_b64 = base64.b64encode(blobfuse2_config_yaml.encode()).decode()
    blobfuse2_unit = _blobfuse2_unit_template.render(
        mount_path=_BLOBFUSE2_MOUNT_PATH, config_path=_BLOBFUSE2_CONFIG_PATH
    )
    blobfuse2_unit_b64 = base64.b64encode(blobfuse2_unit.encode()).decode()
    cloud_init = _cloud_init_template.render(
        admin_username=admin_username,
        blobfuse2_config_b64=blobfuse2_config_b64,
        blobfuse2_unit_b64=blobfuse2_unit_b64,
        blobfuse2_config_path=_BLOBFUSE2_CONFIG_PATH,
        blobfuse2_mount_path=_BLOBFUSE2_MOUNT_PATH,
        blobfuse2_service_name=_BLOBFUSE2_SERVICE_NAME,
    )
    return base64.b64encode(cloud_init.encode()).decode()


custom_data = storage_account.name.apply(  # ty: ignore[missing-argument]
    _custom_data  # ty: ignore[invalid-argument-type]
)

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

# Lives here, not in infra/storage.py, because it needs the VM's identity
# (defined above) and infra/storage.py must stay free of importing this
# module back - it's already imported here for the BlobFuse2 config's
# storage account name, and Python can't resolve an import cycle between
# the two.
storage_blob_data_reader_role_assignment = authorization.RoleAssignment(
    "rse-vm-storage-blob-data-reader",
    scope=blob_container.id,
    principal_id=virtual_machine.identity.principal_id,
    principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL,
    role_definition_id=pulumi.Output.concat(
        "/subscriptions/",
        authorization.get_client_config_output().subscription_id,
        "/providers/Microsoft.Authorization/roleDefinitions/",
        _STORAGE_BLOB_DATA_READER_ROLE_GUID,
    ),
)

# Register with Log Analytics workspace
azure_monitor_extension = compute.VirtualMachineExtension(
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
data_collection_rule_association = monitor.DataCollectionRuleAssociation(
    "rse-dcra-to-dcr",
    association_name="rse-dcr-vms-association",  # this name is required
    data_collection_rule_id=data_collection_rule_vms.id,
    resource_uri=virtual_machine.id,
    opts=ResourceOptions(parent=virtual_machine),
)

# Register with data collection endpoint
data_collection_endpoint_association = monitor.DataCollectionRuleAssociation(
    "rse-dcra-to-dce",
    association_name="configurationAccessEndpoint",  # this name is required
    data_collection_endpoint_id=data_collection_endpoint.id,
    resource_uri=virtual_machine.id,
    opts=ResourceOptions(parent=virtual_machine),
)
