"""Azure infrastructure resource definitions."""

from pulumi_azure_native import resources

resource_group = resources.ResourceGroup("rse-cloud-cybersecurity-rg")
