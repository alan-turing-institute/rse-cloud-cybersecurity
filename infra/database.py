"""Azure SQL Database (Basic tier — the cheapest managed RDBMS on Azure),
reachable over the public internet at this stage (see
specs/00-the-scenario.md).

The VM's managed identity authenticates to the database via Azure AD
(Entra ID) auth, scoped at the database level to db_datareader/db_datawriter
only (see specs/01-managing-identity.md and
scripts/grant-vm-db-access.sh — that grant is SQL DDL, not something
expressible as a Pulumi/ARM resource). The SQL admin login/password below
are kept only because Azure SQL Database requires at least one server admin
at creation, and for management purposes (see specs/01-managing-identity.md)
— the VM's own access path no longer depends on them.
"""

import os

import pulumi
import pulumi_random
from pulumi_azure_native import sql

from infra.naming import suffix
from infra.resource_group import resource_group

_AAD_ADMINISTRATOR_NAME = "ActiveDirectory"

config = pulumi.Config()
admin_username = config.get("db-admin-username") or "sqladmin"

# The Azure AD administrator's identity is supplied via the environment,
# not Pulumi config, so it stays out of source control and can vary per
# person running `pulumi up`/the test suite (see specs/01-managing-identity.md).
aad_admin_object_id = os.environ["AAD_ADMIN_OBJECT_ID"]
aad_admin_login = os.environ["AAD_ADMIN_LOGIN"]

db_admin_password = pulumi_random.RandomPassword(
    "rse-db-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

sql_server = sql.Server(
    "rse-sql-server",
    resource_group_name=resource_group.name,
    server_name=pulumi.Output.concat("rse-cybersecurity-sql-", suffix.result),
    administrator_login=admin_username,
    administrator_login_password=db_admin_password.result,
    version="12.0",
)

sql_server_aad_administrator = sql.ServerAzureADAdministrator(
    "rse-sql-aad-admin",
    resource_group_name=resource_group.name,
    server_name=sql_server.name,
    administrator_name=_AAD_ADMINISTRATOR_NAME,
    administrator_type=sql.AdministratorType.ACTIVE_DIRECTORY,
    login=aad_admin_login,
    sid=aad_admin_object_id,
)

# No VNet integration at this stage, so the server is public - open the
# firewall to the full public range rather than leaving it unreachable.
sql_firewall_rule = sql.FirewallRule(
    "rse-sql-allow-all",
    resource_group_name=resource_group.name,
    server_name=sql_server.name,
    start_ip_address="0.0.0.0",
    end_ip_address="255.255.255.255",
)

sql_database = sql.Database(
    "rse_demo_db",
    resource_group_name=resource_group.name,
    server_name=sql_server.name,
    database_name="rse_demo_db",
    sku=sql.SkuArgs(name="Basic", tier="Basic"),
)
