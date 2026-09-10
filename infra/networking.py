"""Networking resources for the virtual machine.

The VM's network interface has no public IP of its own - it was removed when
Azure Bastion was added (see specs/consolidating-bastion.md). The VM is
reached via the Bastion host (infra/bastion.py) for the general case, or via
the Application Firewall's NAT rule (infra/firewall.py) for a narrower demo
path - see README-Bastion.md and README-Firewall.md. The NSG below (allowing
inbound SSH/RDP from the Internet) is defence in depth rather than the
actual way in, now that nothing here carries a direct public IP; outbound
traffic from vm_subnet is routed through the Application Firewall via
`route_table` (populated by infra/firewall.py, not this module - see the
`ignore_changes` note below).
"""

from pulumi import ResourceOptions
from pulumi_azure_native import network

from infra.resource_group import resource_group

# Define route table
route_table = network.RouteTable(
    "rse-route-table",
    resource_group_name=resource_group.name,
    route_table_name="rse-route-table",
    routes=[],
    opts=ResourceOptions(
        ignore_changes=["routes"]
    ),  # allow routes to be created outside this definition
)

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
    route_table=network.RouteTableArgs(id=route_table.id),
    service_endpoints=[
        network.ServiceEndpointPropertiesFormatArgs(
            service="Microsoft.Storage",
        )
    ],
)

network_interface = network.NetworkInterface(
    "rse-vm-nic",
    resource_group_name=resource_group.name,
    ip_configurations=[
        network.NetworkInterfaceIPConfigurationArgs(
            name="rse-vm-ip-config",
            subnet=network.SubnetArgs(id=vm_subnet.id),
        )
    ],
)
