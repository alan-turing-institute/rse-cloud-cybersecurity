"""Azure SQL Database (Basic tier — the cheapest managed RDBMS on Azure),
using SQL authentication and reachable over the public internet at this
stage (see specs/01-the-scenario.md).
"""

import pulumi
import pulumi_random
from pulumi_azure_native import sql

from infra.naming import suffix
from infra.resource_group import resource_group

config = pulumi.Config()
admin_username = config.get("db-admin-username") or "sqladmin"

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
