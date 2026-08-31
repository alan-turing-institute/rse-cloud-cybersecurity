from pulumi import ResourceOptions
from pulumi_azure_native import monitor, network, operationalinsights

from infra.networking import virtual_network
from infra.resource_group import resource_group

# Create the Log Analytics workspace
workspace_analytics = operationalinsights.Workspace(
    resource_name="rse-log-analytics",
    resource_group_name=resource_group.name,
    retention_in_days=30,
    sku=operationalinsights.WorkspaceSkuArgs(
        name=operationalinsights.WorkspaceSkuNameEnum.PER_GB2018,
    ),
    workspace_name="rse-log-analytics",
)

# Create a data collection endpoint
data_collection_endpoint = monitor.DataCollectionEndpoint(
    "rse-data-collection-endpoint",
    data_collection_endpoint_name="rse-dce-vms",
    network_acls=monitor.DataCollectionEndpointNetworkAclsArgs(
        public_network_access=monitor.KnownPublicNetworkAccessOptions.DISABLED,
    ),
    resource_group_name=resource_group.name,
)

# Create a data collection rule for VM logs
data_collection_rule_vms = monitor.DataCollectionRule(
    "rse-data-collection-rule-vms",
    data_collection_rule_name="rse-dcr-vms",
    data_collection_endpoint_id=data_collection_endpoint.id,
    destinations=monitor.DataCollectionRuleDestinationsArgs(
        log_analytics=[
            monitor.LogAnalyticsDestinationArgs(
                name=workspace_analytics.name,
                workspace_resource_id=workspace_analytics.id,
            )
        ],
    ),
    data_flows=[
        monitor.DataFlowArgs(
            destinations=[workspace_analytics.name],
            streams=[
                monitor.KnownDataFlowStreams.MICROSOFT_PERF,
            ],
            transform_kql="source",
            output_stream=monitor.KnownDataFlowStreams.MICROSOFT_PERF,
        ),
        monitor.DataFlowArgs(
            destinations=[workspace_analytics.name],
            streams=[
                monitor.KnownDataFlowStreams.MICROSOFT_SYSLOG,
            ],
            transform_kql="source",
            output_stream=monitor.KnownDataFlowStreams.MICROSOFT_SYSLOG,
        ),
    ],
    data_sources=monitor.DataCollectionRuleDataSourcesArgs(
        performance_counters=[
            monitor.PerfCounterDataSourceArgs(
                counter_specifiers=[
                    "Processor(*)\\% Processor Time",
                    "Memory(*)\\% Used Memory",
                    "Logical Disk(*)\\% Used Space",
                    "System(*)\\Unique Users",
                ],
                name="LinuxPerfCounters",
                sampling_frequency_in_seconds=60,
                streams=[
                    monitor.KnownPerfCounterDataSourceStreams.MICROSOFT_PERF,
                ],
            ),
        ],
        syslog=[
            monitor.SyslogDataSourceArgs(
                facility_names=[
                    # Note that ASTERISK is not currently working
                    monitor.KnownSyslogDataSourceFacilityNames.ALERT,
                    monitor.KnownSyslogDataSourceFacilityNames.AUDIT,
                    monitor.KnownSyslogDataSourceFacilityNames.AUTH,
                    monitor.KnownSyslogDataSourceFacilityNames.AUTHPRIV,
                    monitor.KnownSyslogDataSourceFacilityNames.CLOCK,
                    monitor.KnownSyslogDataSourceFacilityNames.CRON,
                    monitor.KnownSyslogDataSourceFacilityNames.DAEMON,
                    monitor.KnownSyslogDataSourceFacilityNames.FTP,
                    monitor.KnownSyslogDataSourceFacilityNames.KERN,
                    monitor.KnownSyslogDataSourceFacilityNames.LPR,
                    monitor.KnownSyslogDataSourceFacilityNames.MAIL,
                    monitor.KnownSyslogDataSourceFacilityNames.MARK,
                    monitor.KnownSyslogDataSourceFacilityNames.NEWS,
                    monitor.KnownSyslogDataSourceFacilityNames.NOPRI,
                    monitor.KnownSyslogDataSourceFacilityNames.NTP,
                    monitor.KnownSyslogDataSourceFacilityNames.SYSLOG,
                    monitor.KnownSyslogDataSourceFacilityNames.USER,
                    monitor.KnownSyslogDataSourceFacilityNames.UUCP,
                ],
                log_levels=[
                    # Note that ASTERISK is not currently working
                    monitor.KnownSyslogDataSourceLogLevels.DEBUG,
                    monitor.KnownSyslogDataSourceLogLevels.INFO,
                    monitor.KnownSyslogDataSourceLogLevels.NOTICE,
                    monitor.KnownSyslogDataSourceLogLevels.WARNING,
                    monitor.KnownSyslogDataSourceLogLevels.ERROR,
                    monitor.KnownSyslogDataSourceLogLevels.CRITICAL,
                    monitor.KnownSyslogDataSourceLogLevels.ALERT,
                    monitor.KnownSyslogDataSourceLogLevels.EMERGENCY,
                ],
                name="LinuxSyslog",
                streams=[monitor.KnownSyslogDataSourceStreams.MICROSOFT_SYSLOG],
            ),
        ],
    ),
    resource_group_name=resource_group.name,
)

# Create a private linkscope
log_analytics_private_link_scope = monitor.PrivateLinkScope(
    "rse-log-analytics-private-link-scope",
    access_mode_settings=monitor.AccessModeSettingsArgs(
        ingestion_access_mode=monitor.AccessMode.PRIVATE_ONLY,
        query_access_mode=monitor.AccessMode.PRIVATE_ONLY,
    ),
    location="Global",
    resource_group_name=resource_group.name,
    scope_name="rse-workspace-ampls",
)

# Link the private linkscope to the log analytics workspace
monitor.PrivateLinkScopedResource(
    "rse-log-analytics-ampls-connection",
    kind=monitor.ScopedResourceKind.RESOURCE,
    linked_resource_id=workspace_analytics.id,
    name="rse-cnxn-ampls-to-log-analytics",
    resource_group_name=resource_group.name,
    scope_name=log_analytics_private_link_scope.name,
)

# Link the private linkscope to the data collection endpoint
monitor.PrivateLinkScopedResource(
    "rse-data-collection-endpoint-ampls-connection",
    kind=monitor.ScopedResourceKind.RESOURCE,
    linked_resource_id=data_collection_endpoint.id,
    name="rse-cnxn-ampls-to-dce",
    resource_group_name=resource_group.name,
    scope_name=log_analytics_private_link_scope.name,
)

# Create a network subnet for the private endpoint
subnet_monitoring = network.Subnet(
    "rse-monitoring-subnet",
    resource_group_name=resource_group.name,
    virtual_network_name=virtual_network.name,
    address_prefix="10.0.3.0/24",
)

# Create a private endpoint for the log analytics workspace
log_analytics_private_endpoint = network.PrivateEndpoint(
    "rse-log-analytics-private-endpoint",
    private_endpoint_name="rse-pep-log-analytics",
    resource_group_name=resource_group.name,
    private_link_service_connections=[
        network.PrivateLinkServiceConnectionArgs(
            group_ids=["azuremonitor"],
            name="rse-cnxn-ampls-to-pep-log-analytics",
            private_link_service_id=log_analytics_private_link_scope.id,
        )
    ],
    subnet=network.SubnetArgs(id=subnet_monitoring.id),
    opts=ResourceOptions(
        depends_on=[log_analytics_private_link_scope],
    ),
)
