from pulumi_azure_native import network

from infra.networking import bastion_public_ip, bastion_subnet
from infra.resource_group import resource_group

bastion_host = network.BastionHost(
    "app-bastion",
    bastion_host_name="app-bastion-resource",
    ip_configurations=[
        network.BastionHostIPConfigurationArgs(
            subnet=network.SubResourceArgs(id=bastion_subnet.id),
            name="app-bastion-ip-config",
            public_ip_address=network.SubResourceArgs(id=bastion_public_ip.id),
        )
    ],
    resource_group_name=resource_group.name,
    enable_file_copy=False,
    enable_kerberos=False,
    enable_private_only_bastion=False,
    enable_session_recording=False,
    enable_shareable_link=True,
    enable_tunneling=True,
    enable_ip_connect=True,
    disable_copy_paste=True,
    sku=network.SkuArgs(name="Standard"),
)
