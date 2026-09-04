"""Azure infrastructure resource definitions, split by concern.

Re-exports every resource at the package level so `__main__.py` and the test
suite can import from `infra` directly, e.g. `from infra import storage_account`.
"""

from infra.compute import (
    storage_blob_data_reader_role_assignment,
    virtual_machine,
    vm_admin_password,
)
from infra.database import (
    admin_username,
    db_admin_password,
    sql_database,
    sql_firewall_rule,
    sql_server,
)
from infra.networking import (
    network_interface,
    network_security_group,
    public_ip,
    virtual_network,
    vm_subnet,
)
from infra.resource_group import resource_group
from infra.storage import blob_container, storage_account

__all__ = [
    "admin_username",
    "blob_container",
    "db_admin_password",
    "network_interface",
    "network_security_group",
    "public_ip",
    "resource_group",
    "sql_database",
    "sql_firewall_rule",
    "sql_server",
    "storage_account",
    "storage_blob_data_reader_role_assignment",
    "virtual_machine",
    "virtual_network",
    "vm_admin_password",
    "vm_subnet",
]
