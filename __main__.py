"""Pulumi program entry point."""

import pulumi
from pulumi_azure_native import storage

from infra import (
    resource_group,
    storage_account,
)

storage_account_keys = storage.list_storage_account_keys_output(
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
)

pulumi.export("resource_group_name", resource_group.name)
pulumi.export("storage_account_name", storage_account.name)
pulumi.export(
    "storage_account_primary_key",
    pulumi.Output.secret(storage_account_keys.keys[0].value),
)
