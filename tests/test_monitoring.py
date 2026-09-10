"""Tests for infra.monitoring using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.monitoring import (
    data_collection_endpoint,
    data_collection_rule_vms,
    log_analytics_private_endpoint,
    log_analytics_private_link_scope,
    subnet_monitoring,
    workspace_analytics,
)


class TestMonitoring(unittest.TestCase):
    @pulumi.runtime.test
    def test_workspace_analytics_urn(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-log-analytics", urn)

        return workspace_analytics.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_workspace_analytics_retention_and_sku(self):
        def check(args: tuple) -> None:
            retention_in_days, sku = args
            self.assertEqual(retention_in_days, 30)
            self.assertEqual(sku["name"], "PerGB2018")

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            workspace_analytics.retention_in_days, workspace_analytics.sku
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_data_collection_endpoint_disables_public_network_access(self):
        def check(network_acls) -> None:
            self.assertEqual(network_acls.public_network_access, "Disabled")

        return data_collection_endpoint.network_acls.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_data_collection_rule_sends_perf_and_syslog_to_the_workspace(self):
        def check(args: tuple) -> None:
            destinations, data_flows = args
            self.assertEqual(len(destinations["log_analytics"]), 1)
            streams = {stream for flow in data_flows for stream in flow["streams"]}
            self.assertEqual(streams, {"Microsoft-Perf", "Microsoft-Syslog"})

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            data_collection_rule_vms.destinations, data_collection_rule_vms.data_flows
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_data_collection_rule_collects_cpu_and_memory_perf_counters(self):
        def check(data_sources: dict) -> None:
            counters = data_sources["performance_counters"][0]["counter_specifiers"]
            self.assertIn("Processor(*)\\% Processor Time", counters)
            self.assertIn("Memory(*)\\% Used Memory", counters)

        return data_collection_rule_vms.data_sources.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_private_link_scope_is_private_only(self):
        def check(access_mode_settings) -> None:
            self.assertEqual(access_mode_settings.ingestion_access_mode, "PrivateOnly")
            self.assertEqual(access_mode_settings.query_access_mode, "PrivateOnly")

        return log_analytics_private_link_scope.access_mode_settings.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )

    @pulumi.runtime.test
    def test_monitoring_subnet_uses_a_distinct_address_space(self):
        def check(address_prefix: str) -> None:
            self.assertEqual(address_prefix, "10.0.3.0/24")

        return subnet_monitoring.address_prefix.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

    @pulumi.runtime.test
    def test_log_analytics_private_endpoint_uses_the_monitoring_subnet(self):
        def check(args: tuple) -> None:
            endpoint_subnet_id, subnet_id = args
            self.assertEqual(endpoint_subnet_id, subnet_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            log_analytics_private_endpoint.subnet.id, subnet_monitoring.id
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_log_analytics_private_endpoint_targets_azuremonitor(self):
        def check(connections: list) -> None:
            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].group_ids, ["azuremonitor"])

        return log_analytics_private_endpoint.private_link_service_connections.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )
