from pulumi_azure_native import monitor

from infra.monitoring import workspace_analytics
from infra.resource_group import resource_group

# Change to your email address
# The example address is invalid and will fail during deployment
email_address = "email @ example.com"

# Create an action group for sending an email alert to a specific address
action_group = monitor.ActionGroup(
    "rse-alert-action-group",
    enabled=True,
    resource_group_name=resource_group.name,
    email_receivers=[
        monitor.MicrosoftCommonEmailReceiverArgs(
            email_address=email_address,
            name="rse-email-action",
            use_common_alert_schema=False,
        ),
    ],
    location="Global",
    group_short_name="RSE-Monitor",
)

# Create a metric alert to detect high CPU usage
cpu_alert = monitor.MetricAlert(
    "rse-cpu-metric-alert",
    resource_group_name=resource_group.name,
    window_size="PT5M",  # Five minute window
    criteria=monitor.MetricAlertSingleResourceMultipleMetricCriteriaArgs(
        all_of=[
            monitor.MetricCriteriaArgs(
                metric_name="Average_% Processor Time",
                name="rse_cpu_metric",
                operator=monitor.Operator.GREATER_THAN,
                threshold=90,
                time_aggregation=monitor.AggregationTypeEnum.AVERAGE,
                metric_namespace=workspace_analytics.type,
                skip_metric_validation=False,
                criterion_type="StaticThresholdCriterion",
            ),
        ],
        odata_type="Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
    ),
    severity=2,  # Warning
    enabled=True,
    evaluation_frequency="PT1M",  # 1 minute intervals
    scopes=[
        workspace_analytics.id  # Log Analytics workspace
    ],
    description="Averate CPU utilisation goes above 90%",
    rule_name="rse-cpu-rule",
    location="Global",
    actions=[
        monitor.MetricAlertActionArgs(
            action_group_id=action_group.id,
            web_hook_properties={},
        ),
    ],
    target_resource_region=workspace_analytics.location,
    target_resource_type=workspace_analytics.type,
    auto_mitigate=True,
)

# Create a metric alert to detect high memory usage
mem_alert = monitor.MetricAlert(
    "rse-memory-metric-alert",
    resource_group_name=resource_group.name,
    window_size="PT5M",  # Five minute window
    criteria=monitor.MetricAlertSingleResourceMultipleMetricCriteriaArgs(
        all_of=[
            monitor.MetricCriteriaArgs(
                metric_name="Average_% Used Memory",
                name="rse_mem_metric",
                operator=monitor.Operator.GREATER_THAN,
                threshold=75,
                time_aggregation=monitor.AggregationTypeEnum.AVERAGE,
                metric_namespace=workspace_analytics.type,
                skip_metric_validation=False,
                criterion_type="StaticThresholdCriterion",
            ),
        ],
        odata_type="Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
    ),
    severity=2,  # Warning
    enabled=True,
    evaluation_frequency="PT1M",  # 1 minute intervals
    scopes=[
        workspace_analytics.id  # Log Analytics workspace
    ],
    description="Averate memory utilisation goes above 75%",
    rule_name="rse-mem-rule",
    location="Global",
    actions=[
        monitor.MetricAlertActionArgs(
            action_group_id=action_group.id,
            web_hook_properties={},
        ),
    ],
    target_resource_region=workspace_analytics.location,
    target_resource_type=workspace_analytics.type,
    auto_mitigate=True,
)
