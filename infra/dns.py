from pulumi_azure_native import network, privatedns

from infra.monitoring import log_analytics_private_endpoint
from infra.networking import virtual_network
from infra.resource_group import resource_group

# The DNS zones needed for the monitoring endpoint
dns_zones = {
    "monitor": "privatelink.monitor.azure.com",
    "oms": "privatelink.oms.opinsights.azure.com",
    "ods": "privatelink.ods.opinsights.azure.com",
    "agentsvc": "privatelink.agentsvc.azure-automation.net",
    "blob": "privatelink.blob.core.windows.net",
}

# Create all of the private DNS zones and virtual network links
dns_id = {}
for name, dns in dns_zones.items():
    private_dns_zone = privatedns.PrivateZone(
        f"rse-{name}-private-dns-zone",
        resource_group_name=resource_group.name,
        private_zone_name=dns,
        location="Global",
    )
    privatedns.VirtualNetworkLink(
        resource_name=f"rse-{name}-private-dns-vnet-link",
        location="Global",
        private_zone_name=private_dns_zone.name,
        registration_enabled=False,
        resource_group_name=resource_group.name,
        virtual_network=privatedns.SubResourceArgs(
            id=virtual_network.id,
        ),
        virtual_network_link_name="link-to-rse-vnet",
    )
    dns_id[name] = private_dns_zone.id

# Add a private DNS record for each log analytics workspace custom DNS config
monitoring_dns_zone = network.PrivateDnsZoneGroup(
    "rse-log-analytics-private-dns-zone-group",
    private_dns_zone_configs=[
        network.PrivateDnsZoneConfigArgs(
            name=f"rse-log-to-{name}",
            private_dns_zone_id=dns_id[name],
        )
        for name in dns_id.keys()
    ],
    private_dns_zone_group_name="rse-dzg-log",
    private_endpoint_name=log_analytics_private_endpoint.name,
    resource_group_name=resource_group.name,
)
