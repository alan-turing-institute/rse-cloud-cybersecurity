"""Tests for infra.dns using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.dns import dns_zones, monitoring_dns_zone


class TestDns(unittest.TestCase):
    def test_defines_the_five_monitoring_private_link_domains(self):
        self.assertEqual(
            set(dns_zones.values()),
            {
                "privatelink.monitor.azure.com",
                "privatelink.oms.opinsights.azure.com",
                "privatelink.ods.opinsights.azure.com",
                "privatelink.agentsvc.azure-automation.net",
                "privatelink.blob.core.windows.net",
            },
        )

    @pulumi.runtime.test
    def test_monitoring_dns_zone_group_covers_every_domain(self):
        def check(configs: list) -> None:
            self.assertEqual(len(configs), len(dns_zones))
            names = {config.name for config in configs}
            self.assertEqual(names, {f"rse-log-to-{name}" for name in dns_zones})

        return monitoring_dns_zone.private_dns_zone_configs.apply(  # ty: ignore[missing-argument]
            check  # ty: ignore[invalid-argument-type]
        )
