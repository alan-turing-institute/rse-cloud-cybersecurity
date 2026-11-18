from os import getenv

import pulumi
from pulumi import ResourceOptions
from pulumi_azure_native import containerregistry
from pulumi_azure_native import operationalinsights
from pulumi_azure_native import resources
from pulumi_azure_native import app
from pulumi_azure_native import dbforpostgresql

from infra.resource_group import resource_group
from infra.database import db_server

from infra import (
    db_admin_password,
    db_private_endpoint,
    admin_username,
    get_ip_addresses_from_private_endpoint,
    ca_subnet,
)

workspace = operationalinsights.Workspace(
    "app-loganalytics",
    resource_group_name=resource_group.name,
    sku=operationalinsights.WorkspaceSkuArgs(name="PerGB2018"),
    retention_in_days=30,
)

workspace_shared_keys = pulumi.Output.all(
    resource_group.name, workspace.name).apply(
        lambda args: operationalinsights.get_shared_keys(
            resource_group_name=args[0], workspace_name=args[1]
    )
)

managed_env = app.ManagedEnvironment(
    "app-hedgedoc-env",
    resource_group_name=resource_group.name,
    app_logs_configuration=app.AppLogsConfigurationArgs(
        destination="log-analytics",
        log_analytics_configuration=app.LogAnalyticsConfigurationArgs(
            customer_id=workspace.customer_id,
            shared_key=workspace_shared_keys.apply(lambda r: r.primary_shared_key),
        ),
    ),
    vnet_configuration=app.VnetConfigurationArgs(
        infrastructure_subnet_id=ca_subnet.id,
        internal=True
    ),
)

db_hedgedoc_documents_name = "hedgedoc"
db_hedgedoc_documents = dbforpostgresql.Database(
    "app-db-hedgedoc",
    charset="UTF8",
    database_name=db_hedgedoc_documents_name,
    resource_group_name=resource_group.name,
    server_name=db_server.name,
    opts=ResourceOptions(parent=db_server),
)

container_app = app.ContainerApp(
    "app-hedgedoc",
    resource_group_name=resource_group.name,
    managed_environment_id=managed_env.id,
    configuration=app.ConfigurationArgs(
        ingress=app.IngressArgs(external=True, target_port=80),
        registries=[
            app.RegistryCredentialsArgs(
                server="index.docker.io",
                username=getenv("DOCKER_USER"),
                password_secret_ref="registry-token",
            )
        ],
        secrets=[
            app.SecretArgs(name="registry-token", value=getenv("DOCKER_PAT")),
            app.SecretArgs(name="db-admin-password", value=db_admin_password.result),
        ],
    ),
    template=app.TemplateArgs(
        containers=[
            app.ContainerArgs(
                image="quay.io/hedgedoc/hedgedoc:1.12.0",
                name="hedgedoc"[:63],
                env=[
                    app.EnvironmentVarArgs(
                        name="CMD_ALLOW_ANONYMOUS",
                        value="false",
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_DB_DATABASE",
                        value=db_hedgedoc_documents_name,
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_DB_DIALECT",
                        value="postgres",
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_DB_HOST",
                        value=get_ip_addresses_from_private_endpoint(
                            db_private_endpoint).apply(lambda ips: ips[0]
                        ),
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_DB_PASSWORD",
                        #secure_value=db_admin_password,
                        secret_ref="db-admin-password",
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_DB_PORT",
                        value="5432",
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_DB_USERNAME",
                        value=admin_username,
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_EMAIL",
                        value="false",
                    ),
                    app.EnvironmentVarArgs(
                        name="CMD_LOGLEVEL",
                        value="debug",
                    ),
                ],
                resources=app.ContainerResourcesArgs(
                    cpu=2,
                    memory="4Gi",
                ),
#                volume_mounts=[
#                    app.VolumeMountArgs(
#                        mount_path="/files",
#                        volume_name="hedgedoc-files-config-json",
#                    ),
#                ],
            )
        ]
    ),
)

