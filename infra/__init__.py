"""Azure infrastructure resource definitions, split by concern.

Re-exports every resource at the package level so `__main__.py` and the test
suite can import from `infra` directly, e.g. `from infra import storage_account`.
"""

from infra.resource_group import resource_group
from infra.storage import blob_container, storage_account

__all__ = [
    "blob_container",
    "resource_group",
    "storage_account",
]
