"""Shared random suffix for globally-unique Azure resource names (storage
accounts and PostgreSQL servers are both named in a global, not per-account,
namespace).
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
