"""Networking resources for the virtual machine.

No NSG is attached at this stage: the VM is meant to be reachable directly
over the public internet (see specs/01-the-scenario.md - security hardening
is a later iteration).
"""

from pulumi_azure_native import network

from infra.resource_group import resource_group

virtual_network = network.VirtualNetwork(
    "rse-vnet",
    resource_group_name=resource_group.name,
    address_space=network.AddressSpaceArgs(address_prefixes=["10.0.0.0/16"]),
)

vm_subnet = network.Subnet(
    "rse-vm-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.1.0/24",
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
