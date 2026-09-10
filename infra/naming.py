"""Shared random suffix for the storage account's globally-unique name (storage
accounts are named in a global, not per-account, namespace).
"""

import pulumi_random

suffix = pulumi_random.RandomString(
    "rse-global-suffix",
    length=8,
    lower=True,
    upper=False,
    numeric=True,
    special=False,
)
