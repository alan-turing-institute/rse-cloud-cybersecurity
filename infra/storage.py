"""Storage account, reachable over the public internet at this stage."""

import pulumi
from pulumi_azure_native import storage

from infra.naming import suffix
from infra.resource_group import resource_group

storage_account = storage.StorageAccount(
    "app-storage-account",
    resource_group_name=resource_group.name,
    account_name=pulumi.Output.concat("appcontainer", suffix.result),
    kind=storage.Kind.STORAGE_V2,
    sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS),
)

blob_container = storage.BlobContainer(
    "app-demo-container",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
)
