"""Pulumi program entry point."""

import pulumi
from pulumi_azure_native import storage

from infra import (
    db_admin_password,
    resource_group,
    db_server,
    storage_account,
    virtual_machine,
    vm_admin_password,
    container_app,
    bastion_host,
    bastion_public_ip,
    db_admin_username,
    vm_admin_username,
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
pulumi.export("db_server_fqdn", db_server.fully_qualified_domain_name)
pulumi.export("db_admin_username", db_admin_username)
pulumi.export("db_admin_password", pulumi.Output.secret(db_admin_password.result))
pulumi.export("vm_name", virtual_machine.name)
pulumi.export("vm_admin_username", vm_admin_username)
pulumi.export("vm_admin_password", pulumi.Output.secret(vm_admin_password.result))
pulumi.export("hedgedoc_fqdn", container_app.configuration.ingress.fqdn)
pulumi.export("bastion_public_ip", bastion_public_ip.ip_address)
