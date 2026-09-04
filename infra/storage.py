"""Storage account, reachable over the public internet at this stage.

The VM's managed identity gets read-only access to the `rse-demo-container`
blob container specifically (not the whole account) via the Storage Blob
Data Reader RBAC role, scoped to that container — see
specs/01-managing-identity.md. Every other container on the account is out
of the VM's reach.
"""

import pulumi
import pulumi_random
from pulumi_azure_native import authorization, storage

from infra.compute import virtual_machine
from infra.naming import suffix
from infra.resource_group import resource_group

# Storage Blob Data Reader - a fixed, well-known built-in role GUID, the
# same across every Azure tenant.
_STORAGE_BLOB_DATA_READER_ROLE_ID = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"

storage_account = storage.StorageAccount(
    "rse-storage-account",
    resource_group_name=resource_group.name,
    account_name=pulumi.Output.concat("rsecybersec", suffix.result),
    kind=storage.Kind.STORAGE_V2,
    sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS),
)

blob_container = storage.BlobContainer(
    "rse-demo-container",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
)

# Azure requires the roleAssignments resource name to be a GUID.
_vm_storage_role_assignment_id = pulumi_random.RandomUuid(
    "rse-vm-storage-role-assignment-id"
)

_client_config = authorization.get_client_config_output()

vm_storage_role_assignment = authorization.RoleAssignment(
    "rse-vm-storage-blob-data-reader",
    role_assignment_name=_vm_storage_role_assignment_id.result,
    scope=blob_container.id,
    principal_id=virtual_machine.identity.principal_id,
    principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL,
    role_definition_id=pulumi.Output.concat(
        "/subscriptions/",
        _client_config.subscription_id,
        "/providers/Microsoft.Authorization/roleDefinitions/",
        _STORAGE_BLOB_DATA_READER_ROLE_ID,
    ),
)
