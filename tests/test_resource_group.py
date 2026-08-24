"""Tests for infra.resource_group using Pulumi's mocking framework."""

import unittest

import pulumi

from infra.resource_group import resource_group


class TestResourceGroup(unittest.TestCase):
    @pulumi.runtime.test
    def test_resource_group_urn_contains_expected_name(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-cloud-cybersecurity-rg", urn)

        # ty cannot resolve pulumi's overloaded, generic-self `Output.apply`
        # signature used by this mocking pattern.
        return resource_group.urn.apply(  # ty: ignore[missing-argument]
            check_urn  # ty: ignore[invalid-argument-type]
        )
