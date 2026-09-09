"""Storage account, reachable over the public internet at this stage."""

import pulumi
from pulumi_azure_native import authorization, network, storage

from infra.compute import virtual_machine
from infra.dns import dns_id
from infra.naming import suffix
from infra.networking import network_security_group, virtual_network, vm_subnet
from infra.resource_group import resource_group

# Built-in role definition ID for "Storage Blob Data Contributor" - stable
# across all subscriptions/tenants (see
# https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/storage).
_STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"

# Define a subnet for the storage container
# A "Microsoft.Storage" service endpoint must be defined to allow firewall rules
storage_subnet = network.Subnet(
    "rse-storage-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.6.0/24",
    network_security_group=network.NetworkSecurityGroupArgs(
        id=network_security_group.id
    ),
    service_endpoints=[
        network.ServiceEndpointPropertiesFormatArgs(
            service="Microsoft.Storage",
        )
    ],
)

# List the IP addresses or ranges permitted access
ip_rules = [
    storage.IPRuleArgs(
        action=storage.Action.ALLOW,
        i_p_address_or_range="193.60.220.253",
    ),
]

# Create the storage account
# Specify storage service encryption using Microsoft-managed keys
storage_account = storage.StorageAccount(
    "rse-storage-account",
    resource_group_name=resource_group.name,
    account_name=pulumi.Output.concat("rsecybersec", suffix.result),
    kind=storage.Kind.STORAGE_V2,
    sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS),
    allow_blob_public_access=False,
    enable_https_traffic_only=True,
    enable_nfs_v3=True,
    encryption=storage.EncryptionArgs(
        key_source=storage.KeySource.MICROSOFT_STORAGE,
        services=storage.EncryptionServicesArgs(
            blob=storage.EncryptionServiceArgs(
                enabled=True, key_type=storage.KeyType.ACCOUNT
            ),
            file=storage.EncryptionServiceArgs(
                enabled=True, key_type=storage.KeyType.ACCOUNT
            ),
        ),
    ),
    is_hns_enabled=True,
    minimum_tls_version=storage.MinimumTlsVersion.TLS1_2,
    network_rule_set=storage.NetworkRuleSetArgs(
        bypass=storage.Bypass.AZURE_SERVICES,
        default_action=storage.DefaultAction.DENY,
        ip_rules=ip_rules,
        virtual_network_rules=[
            storage.VirtualNetworkRuleArgs(
                virtual_network_resource_id=storage_subnet.id,
            ),
            storage.VirtualNetworkRuleArgs(
                virtual_network_resource_id=vm_subnet.id,
            ),
        ],
    ),
    public_network_access=storage.PublicNetworkAccess.ENABLED,
)

# Create a a blob container within the storage account
blob_container = storage.BlobContainer(
    "rse-demo-container",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
)

# Set up a private endpoint for access to the data storage account
storage_account_private_endpoint = network.PrivateEndpoint(
    "rse-storage-account-private-endpoint",
    private_endpoint_name="rse-pep-storage-account-data-private-sensitive",
    private_link_service_connections=[
        network.PrivateLinkServiceConnectionArgs(
            group_ids=["blob"],
            name="rse-cnxn-pep-storage-account-data-private-sensitive",
            private_link_service_id=storage_account.id,
        )
    ],
    resource_group_name=resource_group.name,
    subnet=network.SubnetArgs(id=storage_subnet.id),
    opts=pulumi.ResourceOptions(
        parent=storage_account,
    ),
)

# Populate the "blob" private DNS zone (created and linked to the whole VNet
# in infra/dns.py, for the Log Analytics private endpoint) with a record for
# this private endpoint too. Without this, the zone is linked but empty: the
# private endpoint's mere existence makes Azure rewrite the storage
# account's public DNS entry to a CNAME into this zone, so any DNS query for
# the storage account from inside the VNet (including the VM) gets shadowed
# by the empty zone and fails to resolve, instead of falling back to the
# account's public IP the way it would from outside the VNet.
storage_account_private_dns_zone_group = network.PrivateDnsZoneGroup(
    "rse-storage-account-private-dns-zone-group",
    private_dns_zone_configs=[
        network.PrivateDnsZoneConfigArgs(
            name="rse-storage-to-blob",
            private_dns_zone_id=dns_id["blob"],
        )
    ],
    private_dns_zone_group_name="rse-dzg-storage",
    private_endpoint_name=storage_account_private_endpoint.name,
    resource_group_name=resource_group.name,
)

# Grant the VM's own system-assigned managed identity data-plane access to
# the storage account, so `az login --identity` on the VM (no interactive
# sign-in, no manual role assignment) is enough for `az storage blob
# upload`/`download --auth-mode login` to work - see README-Storage.md.
# principal_type is set explicitly because the managed identity is created
# in this same deployment; without it, Azure AD replication lag between
# creating the identity and creating this role assignment can make the
# assignment fail validation.
vm_storage_blob_data_contributor = authorization.RoleAssignment(
    "rse-vm-storage-blob-data-contributor",
    principal_id=virtual_machine.identity.principal_id,
    principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL,
    role_definition_id=pulumi.Output.concat(
        resource_group.id,
        "/providers/Microsoft.Authorization/roleDefinitions/",
        _STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID,
    ),
    scope=storage_account.id,
)
