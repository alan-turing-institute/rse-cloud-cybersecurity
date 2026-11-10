"""Shared resource group for all infrastructure in this scenario."""

from pulumi_azure_native import resources

resource_group = resources.ResourceGroup("subdir-rg")
