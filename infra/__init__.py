"""Azure infrastructure resource definitions, split by concern.

Re-exports every resource at the package level so `__main__.py` and the test
suite can import from `infra` directly, e.g. `from infra import storage_account`.
"""

from infra.compute import virtual_machine, vm_admin_password
from infra.database import (
    admin_username,
    postgres_admin_password,
    postgres_database,
    postgres_firewall_rule,
    postgres_server,
)
from infra.networking import network_interface, public_ip, virtual_network, vm_subnet
from infra.resource_group import resource_group
from infra.storage import blob_container, storage_account

__all__ = [
    "admin_username",
    "blob_container",
    "network_interface",
    "postgres_admin_password",
    "postgres_database",
    "postgres_firewall_rule",
    "postgres_server",
    "public_ip",
    "resource_group",
    "storage_account",
    "virtual_machine",
    "virtual_network",
    "vm_admin_password",
    "vm_subnet",
]
