"""Tests for infra.py using Pulumi's mocking framework."""

import unittest

import pulumi


class PulumiMocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        return [f"{args.name}_id", args.inputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


pulumi.runtime.set_mocks(PulumiMocks())

import infra  # noqa: E402 - must be imported after mocks are configured


class TestInfra(unittest.TestCase):
    @pulumi.runtime.test
    def test_resource_group_urn_contains_expected_name(self):
        def check_urn(urn: str) -> None:
            self.assertIn("rse-cloud-cybersecurity-rg", urn)

        # ty cannot resolve pulumi's overloaded, generic-self `Output.apply`
        # signature used by this mocking pattern.
        return infra.resource_group.urn.apply(  # ty: ignore[missing-argument]
            check_urn  # ty: ignore[invalid-argument-type]
        )
