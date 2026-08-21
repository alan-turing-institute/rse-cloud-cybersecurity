"""Networking resources for the virtual machine.

The VM is meant to be reachable directly over the public internet (see
specs/01-the-scenario.md - security hardening is a later iteration). The one
exception is a minimal NSG allowing inbound SSH and RDP from anywhere, added
purely so the VM (and its graphical desktop) is reachable for the demo - it
is not a security boundary, and every other port stays open via the default
allow-all rules.
"""

from pulumi_azure_native import network

from infra.resource_group import resource_group

virtual_network = network.VirtualNetwork(
    "rse-vnet",
    resource_group_name=resource_group.name,
    address_space=network.AddressSpaceArgs(address_prefixes=["10.0.0.0/16"]),
)

network_security_group = network.NetworkSecurityGroup(
    "rse-vm-nsg",
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

vm_subnet = network.Subnet(
    "rse-vm-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.1.0/24",
    network_security_group=network.NetworkSecurityGroupArgs(
        id=network_security_group.id
    ),
)

public_ip = network.PublicIPAddress(
    "rse-vm-public-ip",
    resource_group_name=resource_group.name,
    sku=network.PublicIPAddressSkuArgs(name=network.PublicIPAddressSkuName.STANDARD),
    public_ip_allocation_method=network.IPAllocationMethod.STATIC,
)

network_interface = network.NetworkInterface(
    "rse-vm-nic",
    resource_group_name=resource_group.name,
    ip_configurations=[
        network.NetworkInterfaceIPConfigurationArgs(
            name="rse-vm-ip-config",
            subnet=network.SubnetArgs(id=vm_subnet.id),
            public_ip_address=network.PublicIPAddressArgs(id=public_ip.id),
        )
    ],
)
