from pulumi import Output, ResourceOptions
from pulumi_azure_native import network

from infra.networking import network_interface, virtual_network, vm_subnet
from infra.resource_group import resource_group

# Firewall subnet
firewall_subnet = network.Subnet(
    "AzureFirewallSubnet",  # This name is required by Azure
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.4.0/24",  # 64 address minimum
    # Note that NSGs cannot be attached to a subnet containing a firewall
)

# Firewall management subnet
firewall_management_subnet = network.Subnet(
    "AzureFirewallManagementSubnet",  # This name is required by Azure
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.5.0/24",  # 64 address minimum
    # Note that NSGs cannot be attached to a subnet containing a firewall
)

# Deploy an IP address for the Firewall
firewall_public_ip = network.PublicIPAddress(
    "rse-pip-firewall",
    public_ip_address_name="rse-pip-firewall",
    public_ip_allocation_method=network.IPAllocationMethod.STATIC,
    resource_group_name=resource_group.name,
    sku=network.PublicIPAddressSkuArgs(name=network.PublicIPAddressSkuName.STANDARD),
)

# A Basic SKU firewall needs a separate management IP address and subnet to
# handle traffic for communicating updates and health metrics to and from
# Microsoft
firewall_management_public_ip = network.PublicIPAddress(
    "rse-pip-firewall-management",
    public_ip_address_name="rse-pip-firewall-management",
    public_ip_allocation_method=network.IPAllocationMethod.STATIC,
    resource_group_name=resource_group.name,
    sku=network.PublicIPAddressSkuArgs(name=network.PublicIPAddressSkuName.STANDARD),
)

# No network rules needed for this example
network_rule_collections = []

# Add a NAT rule to allow external connections to SSH to the VM
nat_rule_collections = [
    network.AzureFirewallNatRuleCollectionArgs(
        action=network.AzureFirewallNatRCActionArgs(
            type=network.AzureFirewallNatRCActionType.DNAT,
        ),
        name="workspaces-allow-ssh",
        priority=200,
        rules=[
            network.AzureFirewallNatRuleArgs(
                description="Allow incoming SSH requests",
                name="AllowSsh",
                protocols=[
                    network.AzureFirewallNetworkRuleProtocol.TCP,
                ],
                source_addresses=["193.60.220.253"],
                source_ip_groups=[],
                destination_addresses=Output.all(firewall_public_ip.ip_address),
                destination_ports=["22"],
                translated_address=network_interface.ip_configurations[
                    0
                ].private_ip_address,
                translated_port="22",
            ),
        ],
    ),
]

# Rules to allow outgoing connections to public sites
# Other outgoing connections will be blocked
application_rule_collections = [
    network.AzureFirewallApplicationRuleCollectionArgs(
        action=network.AzureFirewallRCActionArgs(
            type=network.AzureFirewallRCActionType.ALLOW
        ),
        name="workspaces-allow-restricted",
        priority=1000,
        rules=[
            network.AzureFirewallApplicationRuleArgs(
                description="Allow external Ubuntu keyserver requests",
                name="AllowUbuntuKeyserver",
                protocols=[
                    network.AzureFirewallApplicationRuleProtocolArgs(
                        port=11371,
                        protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTP,
                    ),
                ],
                source_addresses=vm_subnet.address_prefixes,
                target_fqdns=[
                    "keyserver.ubuntu.com",
                ],
            ),
            network.AzureFirewallApplicationRuleArgs(
                description="Allow external Ubuntu Snap Store access",
                name="AllowUbuntuSnapcraft",
                protocols=[
                    network.AzureFirewallApplicationRuleProtocolArgs(
                        port=443,
                        protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTPS,
                    ),
                ],
                source_addresses=vm_subnet.address_prefixes,
                target_fqdns=[
                    "api.snapcraft.io",
                    "*.snapcraftcontent.com",
                ],
            ),
            network.AzureFirewallApplicationRuleArgs(
                description="Allow external RStudio deb downloads",
                name="AllowRStudioDeb",
                protocols=[
                    network.AzureFirewallApplicationRuleProtocolArgs(
                        port=443,
                        protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTPS,
                    ),
                ],
                source_addresses=vm_subnet.address_prefixes,
                target_fqdns=[
                    "download1.rstudio.org",
                ],
            ),
        ],
    ),
    network.AzureFirewallApplicationRuleCollectionArgs(
        action=network.AzureFirewallRCActionArgs(
            type=network.AzureFirewallRCActionType.DENY
        ),
        name="workspaces-deny",
        priority=2000,
        rules=[
            network.AzureFirewallApplicationRuleArgs(
                description="Deny external Ubuntu Snap Store upload and login access",
                name="DenyUbuntuSnapcraft",
                protocols=[
                    network.AzureFirewallApplicationRuleProtocolArgs(
                        port=80,
                        protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTP,
                    ),
                    network.AzureFirewallApplicationRuleProtocolArgs(
                        port=443,
                        protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTPS,
                    ),
                ],
                source_addresses=vm_subnet.address_prefixes,
                target_fqdns=[
                    "dashboard.snapcraft.io",  # upload endpoint
                    "login.ubuntu.com",  # login endpoint (provides auth for upload)
                    "upload.apps.ubuntu.com",
                ],
            ),
        ],
    ),
]

# Deploy the firewall
firewall = network.AzureFirewall(
    "rse-firewall",
    nat_rule_collections=nat_rule_collections,
    application_rule_collections=application_rule_collections,
    azure_firewall_name="rse-firewall",
    ip_configurations=[
        network.AzureFirewallIPConfigurationArgs(
            name="FirewallIpConfiguration",
            public_ip_address=network.SubResourceArgs(id=firewall_public_ip.id),
            subnet=network.SubResourceArgs(id=firewall_subnet.id),
        )
    ],
    management_ip_configuration=network.AzureFirewallIPConfigurationArgs(
        name="FirewallManagementIpConfiguration",
        public_ip_address=network.SubResourceArgs(id=firewall_management_public_ip.id),
        subnet=network.SubResourceArgs(id=firewall_management_subnet.id),
    ),
    network_rule_collections=network_rule_collections,
    resource_group_name=resource_group.name,
    sku=network.AzureFirewallSkuArgs(
        name=network.AzureFirewallSkuName.AZF_W_V_NET,
        tier=network.AzureFirewallSkuTier.BASIC,
    ),
)

# Route all external traffic through the firewall
#
# We use the system default route "0.0.0.0/0" as this will be overruled by
# anything more specific, such as VNet <-> VNet traffic which we do not want to
# send via the firewall.
#
# See https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview
route = network.Route(
    "rse-route-via-firewall",
    address_prefix="0.0.0.0/0",
    next_hop_ip_address=firewall.ip_configurations[0].private_ip_address,
    next_hop_type=network.RouteNextHopType.VIRTUAL_APPLIANCE,
    resource_group_name=resource_group.name,
    route_name="ViaFirewall",
    route_table_name="rse-route-table",
    opts=ResourceOptions(parent=firewall),
)
