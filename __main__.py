"""Pulumi program entry point."""

import pulumi
from pulumi_azure_native import storage

from infra import (
    bastion_host,
    bastion_public_ip,
    firewall_public_ip,
    resource_group,
    storage_account,
    virtual_machine,
    vm_admin_password,
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
pulumi.export("vm_name", virtual_machine.name)
pulumi.export("vm_id", virtual_machine.id)
pulumi.export("vm_admin_password", pulumi.Output.secret(vm_admin_password.result))
pulumi.export("bastion_name", bastion_host.name)
pulumi.export("bastion_id", bastion_host.id)
pulumi.export("bastion_public_ip", bastion_public_ip.ip_address)
pulumi.export("firewall_public_ip", firewall_public_ip.ip_address)
