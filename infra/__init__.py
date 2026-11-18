"""Azure infrastructure resource definitions, split by concern.

Re-exports every resource at the package level so `__main__.py` and the test
suite can import from `infra` directly, e.g. `from infra import storage_account`.
"""

from infra.compute import virtual_machine, vm_admin_password
from infra.database import (
    admin_username,
    db_admin_password,
    db_server,
    db_private_endpoint,
)
from infra.networking import (
    network_interface,
    network_security_group,
    public_ip,
    virtual_network,
    vm_subnet,
    db_subnet,
    get_ip_addresses_from_private_endpoint,
)
from infra.resource_group import resource_group
from infra.storage import blob_container, storage_account
from infra.app import container_app

__all__ = [
    "admin_username",
    "blob_container",
    "container_app",
    "db_admin_password",
    "db_server",
    "db_private_endpoint",
    "network_interface",
    "network_security_group",
    "public_ip",
    "resource_group",
    "storage_account",
    "virtual_machine",
    "virtual_network",
    "vm_admin_password",
    "vm_subnet",
    "db_subnet",
    "get_ip_addresses_from_private_endpoint",
]
