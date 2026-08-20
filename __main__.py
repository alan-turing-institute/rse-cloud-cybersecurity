"""Pulumi program entry point."""

import pulumi

from infra import resource_group

pulumi.export("resource_group_name", resource_group.name)
