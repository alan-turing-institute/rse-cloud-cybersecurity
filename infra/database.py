"""PostgreSQL Flexible Server, using password auth and reachable over the
public internet at this stage (see specs/01-the-scenario.md).
"""

import pulumi
import pulumi_random
from pulumi_azure_native import dbforpostgresql

from infra.naming import suffix
from infra.resource_group import resource_group

config = pulumi.Config()
admin_username = config.get("db-admin-username") or "pgadmin"

postgres_admin_password = pulumi_random.RandomPassword(
    "rse-postgres-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

postgres_server = dbforpostgresql.Server(
    "rse-postgres-server",
    resource_group_name=resource_group.name,
    server_name=pulumi.Output.concat("rse-cybersecurity-pg-", suffix.result),
    sku=dbforpostgresql.SkuArgs(
        name="Standard_B1ms", tier=dbforpostgresql.SkuTier.BURSTABLE
    ),
    storage=dbforpostgresql.StorageArgs(storage_size_gb=32),
    version=dbforpostgresql.PostgresMajorVersion.POSTGRES_MAJOR_VERSION_17,
    backup=dbforpostgresql.BackupArgs(
        backup_retention_days=7,
        geo_redundant_backup=dbforpostgresql.GeographicallyRedundantBackup.DISABLED,
    ),
    administrator_login=admin_username,
    administrator_login_password=postgres_admin_password.result,
    auth_config=dbforpostgresql.AuthConfigArgs(
        password_auth=dbforpostgresql.PasswordBasedAuth.ENABLED,
    ),
    network=dbforpostgresql.NetworkArgs(
        public_network_access=dbforpostgresql.ServerPublicNetworkAccessState.ENABLED,
    ),
)

# No VNet integration at this stage, so the server is public - open the
# firewall to the full public range rather than leaving it unreachable.
postgres_firewall_rule = dbforpostgresql.FirewallRule(
    "rse-postgres-allow-all",
    resource_group_name=resource_group.name,
    server_name=postgres_server.name,
    start_ip_address="0.0.0.0",
    end_ip_address="255.255.255.255",
)

postgres_database = dbforpostgresql.Database(
    "rse_demo_db",
    resource_group_name=resource_group.name,
    server_name=postgres_server.name,
    database_name="rse_demo_db",
)
