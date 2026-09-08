"""Tests for infra.alerts using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.alerts import action_group, cpu_alert, mem_alert


class TestAlerts(unittest.TestCase):
    @pulumi.runtime.test
    def test_action_group_has_an_enabled_email_receiver(self):
        def check(args: tuple) -> None:
            enabled, email_receivers = args
            self.assertTrue(enabled)
            self.assertEqual(len(email_receivers), 1)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            action_group.enabled, action_group.email_receivers
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_cpu_alert_triggers_above_90_percent(self):
        def check(args: tuple) -> None:
            criteria, enabled, actions, action_group_id = args
            metric = criteria["allOf"][0]
            self.assertEqual(metric["metricName"], "Average_% Processor Time")
            self.assertEqual(metric["threshold"], 90)
            self.assertTrue(enabled)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action_group_id"], action_group_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            cpu_alert.criteria, cpu_alert.enabled, cpu_alert.actions, action_group.id
        ).apply(check)  # ty: ignore[invalid-argument-type]

    @pulumi.runtime.test
    def test_mem_alert_triggers_above_75_percent(self):
        def check(args: tuple) -> None:
            criteria, enabled, actions, action_group_id = args
            metric = criteria["allOf"][0]
            self.assertEqual(metric["metricName"], "Average_% Used Memory")
            self.assertEqual(metric["threshold"], 75)
            self.assertTrue(enabled)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action_group_id"], action_group_id)

        return pulumi.Output.all(  # ty: ignore[missing-argument]
            mem_alert.criteria, mem_alert.enabled, mem_alert.actions, action_group.id
        ).apply(check)  # ty: ignore[invalid-argument-type]
