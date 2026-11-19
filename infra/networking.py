"""Networking resources for the virtual machine.

The VM is meant to be reachable directly over the public internet (see
specs/01-the-scenario.md - security hardening is a later iteration). The one
exception is a minimal NSG allowing inbound SSH and RDP from anywhere, added
purely so the VM (and its graphical desktop) is reachable for the demo - it
is not a security boundary, and every other port stays open via the default
allow-all rules.
"""

from pulumi import Output, ResourceOptions
from pulumi_azure_native import network

from infra.resource_group import resource_group

def get_ip_addresses_from_private_endpoint(
    endpoint: network.PrivateEndpoint,
) -> Output[list[str]]:
    """Get a list of IP addresses from a private endpoint"""
    if isinstance(endpoint.custom_dns_configs, Output):
        return endpoint.custom_dns_configs.apply(
            lambda cfgs: (
                list(
                    {
                        ip_address
                        for cfg in cfgs
                        for ip_address in (cfg.ip_addresses if cfg.ip_addresses else [])
                    }
                )
                if cfgs
                else []
            )
        )
    msg = f"Private endpoint '{endpoint}' has no IP addresses."
    raise Exception(msg)

virtual_network = network.VirtualNetwork(
    "app-vnet",
    resource_group_name=resource_group.name,
    address_space=network.AddressSpaceArgs(address_prefixes=["10.0.0.0/16"]),
)

network_security_group = network.NetworkSecurityGroup(
    "app-vm-nsg",
    resource_group_name=resource_group.name,
    security_rules=[
        network.SecurityRuleArgs(
            name="allow-ssh-from-internet",
            priority=100,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.TCP,
            source_address_prefix="Internet",
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="22",
        ),
        network.SecurityRuleArgs(
            name="allow-rdp-from-internet",
            priority=110,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.TCP,
            source_address_prefix="Internet",
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="3389",
        ),
    ],
)

bastion_network_security_group = network.NetworkSecurityGroup(
    "app-bastion-nsg",
    resource_group_name=resource_group.name,
    security_rules=[
        network.SecurityRuleArgs(
            name="allow-http-inbound",
            priority=100,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.TCP,
            source_address_prefix="Internet",
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="443",
        ),
        network.SecurityRuleArgs(
            name="allow-gateway-manager-inbound",
            priority=120,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.TCP,
            source_address_prefix="GatewayManager",
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="443",
        ),
        network.SecurityRuleArgs(
            name="allow-bastion-host-communication-http",
            priority=130,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="VirtualNetwork",
            source_port_range="*",
            destination_address_prefix="VirtualNetwork",
            destination_port_range="8080",
        ),
        network.SecurityRuleArgs(
            name="allow-bastion-host-communication-hazelcast",
            priority=135,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="VirtualNetwork",
            source_port_range="*",
            destination_address_prefix="VirtualNetwork",
            destination_port_range="5701",
        ),
        network.SecurityRuleArgs(
            name="allow-azure-load-balancer-inbound",
            priority=140,
            direction=network.SecurityRuleDirection.INBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.TCP,
            source_address_prefix="AzureLoadBalancer",
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="443",
        ),
        network.SecurityRuleArgs(
            name="allow-ssh-outbound",
            priority=150,
            direction=network.SecurityRuleDirection.OUTBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="*",
            source_port_range="*",
            destination_address_prefix="VirtualNetwork",
            destination_port_range="22",
        ),
        network.SecurityRuleArgs(
            name="allow-rdp-outbound",
            priority=155,
            direction=network.SecurityRuleDirection.OUTBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="*",
            source_port_range="*",
            destination_address_prefix="VirtualNetwork",
            destination_port_range="3389",
        ),
        network.SecurityRuleArgs(
            name="allow-azure-cloud-outbound",
            priority=160,
            direction=network.SecurityRuleDirection.OUTBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.TCP,
            source_address_prefix="*",
            source_port_range="*",
            destination_address_prefix="AzureCloud",
            destination_port_range="443",
        ),
        network.SecurityRuleArgs(
            name="allow-bastion-communication-http",
            priority=170,
            direction=network.SecurityRuleDirection.OUTBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="VirtualNetwork",
            source_port_range="*",
            destination_address_prefix="VirtualNetwork",
            destination_port_range="8080",
        ),
        network.SecurityRuleArgs(
            name="allow-bastion-communication-hazelcast",
            priority=175,
            direction=network.SecurityRuleDirection.OUTBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="VirtualNetwork",
            source_port_range="*",
            destination_address_prefix="VirtualNetwork",
            destination_port_range="5701",
        ),
        network.SecurityRuleArgs(
            name="allow-http-outbound",
            priority=180,
            direction=network.SecurityRuleDirection.OUTBOUND,
            access=network.SecurityRuleAccess.ALLOW,
            protocol=network.SecurityRuleProtocol.ASTERISK,
            source_address_prefix="*",
            source_port_range="*",
            destination_address_prefix="Internet",
            destination_port_range="80",
        ),
    ],
)

vm_subnet = network.Subnet(
    "app-vm-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.1.0/24",
    network_security_group=network.NetworkSecurityGroupArgs(
        id=network_security_group.id
    ),
)

db_subnet = network.Subnet(
    "app-db-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.2.0/24",
    network_security_group=network.NetworkSecurityGroupArgs(
        id=network_security_group.id
    ),
)

ca_subnet = network.Subnet(
    "app-ca-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.3.0/27",
    network_security_group=network.NetworkSecurityGroupArgs(
        id=network_security_group.id
    ),
    delegations=[
        network.DelegationArgs(
            name="SubnetDelegationContainerApps",
            service_name="Microsoft.App/environments",
            type="Microsoft.Network/virtualNetworks/subnets/delegations",
        ),
    ],
)

bastion_subnet = network.Subnet(
    "AzureBastionSubnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.4.0/24",
    network_security_group=network.NetworkSecurityGroupArgs(
        id=bastion_network_security_group.id
    ),
)

network_interface = network.NetworkInterface(
    "app-vm-nic",
    resource_group_name=resource_group.name,
    ip_configurations=[
        network.NetworkInterfaceIPConfigurationArgs(
            name="app-vm-ip-config",
            subnet=network.SubnetArgs(id=vm_subnet.id),
        )
    ],
)

bastion_public_ip = network.PublicIPAddress(
    "app-bastion-public-ip",
    resource_group_name=resource_group.name,
    sku=network.PublicIPAddressSkuArgs(name=network.PublicIPAddressSkuName.STANDARD),
    public_ip_allocation_method=network.IPAllocationMethod.STATIC,
)
