"""Azure SQL Database (Basic tier — the cheapest managed RDBMS on Azure),
using SQL authentication and reachable over the public internet at this
stage (see specs/01-the-scenario.md).
"""

import pulumi
import pulumi_random
from pulumi import ResourceOptions
from pulumi_azure_native import dbforpostgresql, network

from infra.naming import suffix
from infra.resource_group import resource_group
from infra.networking import db_subnet

config = pulumi.Config()
admin_username = config.get("db-admin-username") or "sqladmin"

db_admin_password = pulumi_random.RandomPassword(
    "app-db-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)

# Define a PostgreSQL server
db_server = dbforpostgresql.Server(
    "app-db-server",
    administrator_login=admin_username,
    administrator_login_password=db_admin_password.result,
    auth_config=dbforpostgresql.AuthConfigArgs(
        active_directory_auth=dbforpostgresql.MicrosoftEntraAuth.DISABLED,
        password_auth=dbforpostgresql.PasswordBasedAuth.ENABLED,
    ),
    backup=dbforpostgresql.BackupArgs(
        backup_retention_days=7,
        geo_redundant_backup=dbforpostgresql.GeographicallyRedundantBackup.DISABLED,
    ),
    create_mode=dbforpostgresql.CreateMode.DEFAULT,
    data_encryption=dbforpostgresql.DataEncryptionArgs(
        type="SystemManaged",
    ),
    high_availability=dbforpostgresql.HighAvailabilityArgs(
        mode=dbforpostgresql.PostgreSqlFlexibleServerHighAvailabilityMode.DISABLED,
    ),
    resource_group_name=resource_group.name,
    server_name=pulumi.Output.concat("app-containerapp-test-db-", suffix.result),
    sku=dbforpostgresql.SkuArgs(
        name="Standard_B2s",
        tier=dbforpostgresql.SkuTier.BURSTABLE,
    ),
    storage=dbforpostgresql.StorageArgs(
        storage_size_gb=32,
    ),
    version=dbforpostgresql.PostgresMajorVersion.POSTGRES_MAJOR_VERSION_14,
)


# Deploy a private endpoint for the PostgreSQL server
db_private_endpoint = network.PrivateEndpoint(
    f"app_db_server_private_endpoint",
    private_endpoint_name="db-server-endpoint",
    private_link_service_connections=[
        network.PrivateLinkServiceConnectionArgs(
            group_ids=["postgresqlServer"],
            name="db-server-privatelink",
            private_link_service_connection_state=network.PrivateLinkServiceConnectionStateArgs(
                actions_required="None",
                description="Auto-approved",
                status="Approved",
            ),
            private_link_service_id=db_server.id,
        )
    ],
    resource_group_name=resource_group.name,
    subnet=network.SubnetArgs(id=db_subnet.id),
    opts=ResourceOptions(parent=db_server),
)
