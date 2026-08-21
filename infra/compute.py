"""Linux virtual machine that can reach the storage account and the SQL
database over the public internet (see specs/01-the-scenario.md - no managed
identity/RBAC yet, storage access uses the account key/connection string
exported as a secret stack output instead).

Uses password authentication rather than an SSH key, in line with delaying
security hardening to a later iteration.

Also carries a graphical desktop (XFCE + xrdp) reachable over RDP, and VS
Code with the mssql/Azure Storage extensions as the expected way to reach
the database and the storage account. The mssql connection profile is
pre-created (server/database/username), but - per the extension's own
documented behaviour - the password isn't something that can be pre-seeded
into settings.json; it's entered once on first connect and then remembered
via VS Code's secret storage (savePassword=true). Likewise the Azure Storage
extension has no documented settings.json key for pre-attaching an account,
so the operator attaches it once via "Attach Storage Account..." using the
connection string handed out as a secret stack output.
"""

import base64
import json

import pulumi
import pulumi_random
from pulumi_azure_native import compute

from infra.database import admin_username as db_admin_username
from infra.database import sql_database, sql_server
from infra.networking import network_interface
from infra.resource_group import resource_group

config = pulumi.Config()
admin_username = config.get("vm-admin-username") or "azureuser"

vm_admin_password = pulumi_random.RandomPassword(
    "rse-vm-admin-password",
    length=24,
    special=True,
    override_special="_%@",
)


def _vscode_settings_json(sql_server_fqdn: str, database_name: str) -> str:
    return json.dumps(
        {
            "mssql.connections": [
                {
                    "profileName": "rse-demo-db",
                    "server": sql_server_fqdn,
                    "database": database_name,
                    "authenticationType": "SqlLogin",
                    "user": db_admin_username,
                    "password": "",
                    "savePassword": True,
                    "encrypt": "Mandatory",
                }
            ]
        }
    )


_PACKAGES = ["unixodbc-dev", "wget", "gpg", "xfce4", "xrdp"]

_AZ_CLI_INSTALL_URL = "https://azurecliprod.blob.core.windows.net/$root/deb_install.sh"
_MSSQL_TOOLS_CONFIG_URL = (
    "https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb"
)
_VSCODE_GPG_KEY_URL = "https://packages.microsoft.com/keys/microsoft.asc"
_VSCODE_KEYRING = "/usr/share/keyrings/microsoft-vscode.gpg"
_VSCODE_SOURCES_LINE = (
    "Types: deb\\nURIs: https://packages.microsoft.com/repos/code\\n"
    "Suites: stable\\nComponents: main\\nArchitectures: amd64,arm64,armhf\\n"
    f"Signed-By: {_VSCODE_KEYRING}\\n"
)


def _runcmd(admin_username: str, vscode_settings_b64: str) -> list:
    home = f"/home/{admin_username}"
    return [
        "systemctl enable --now xrdp",
        f"curl -fsSL '{_AZ_CLI_INSTALL_URL}' | bash",
        f"curl -sSL -O {_MSSQL_TOOLS_CONFIG_URL}",
        "dpkg -i packages-microsoft-prod.deb",
        "rm -f packages-microsoft-prod.deb",
        "apt-get update",
        "ACCEPT_EULA=Y apt-get install -y mssql-tools18",
        "echo 'export PATH=\"$PATH:/opt/mssql-tools18/bin\"'"
        " >> /etc/profile.d/mssql-tools.sh",
        f"wget -qO- {_VSCODE_GPG_KEY_URL} | gpg --dearmor -o {_VSCODE_KEYRING}",
        f"printf '{_VSCODE_SOURCES_LINE}' > /etc/apt/sources.list.d/vscode.sources",
        "apt-get update",
        "apt-get install -y code",
        f"sudo -u {admin_username} -H code --install-extension ms-mssql.mssql --force",
        f"sudo -u {admin_username} -H code --install-extension"
        " ms-azuretools.vscode-azurestorage --force",
        f"mkdir -p {home}/.config/Code/User",
        f"echo '{vscode_settings_b64}' | base64 -d"
        f" > {home}/.config/Code/User/settings.json",
        f"chown -R {admin_username}:{admin_username} {home}/.config",
    ]


def _cloud_init(admin_username: str, vscode_settings_json: str) -> str:
    vscode_settings_b64 = base64.b64encode(vscode_settings_json.encode()).decode()
    packages = "".join(f"\n  - {package}" for package in _PACKAGES)
    # json.dumps() rather than a bare "- {command}": several commands below
    # contain a bare ": " (e.g. the printf'd apt sources file), which YAML
    # treats as a mapping separator in an unquoted scalar; a JSON-quoted
    # string is a valid YAML double-quoted scalar and escapes that safely.
    commands = "".join(
        f"\n  - {json.dumps(command)}"
        for command in _runcmd(admin_username, vscode_settings_b64)
    )
    lines = [
        "#cloud-config",
        "package_update: true",
        f"packages:{packages}",
        f"runcmd:{commands}",
    ]
    return "\n".join(lines) + "\n"


def _custom_data(sql_server_fqdn: str, database_name: str) -> str:
    vscode_settings_json = _vscode_settings_json(sql_server_fqdn, database_name)
    cloud_init = _cloud_init(admin_username, vscode_settings_json)
    return base64.b64encode(cloud_init.encode()).decode()


custom_data = pulumi.Output.all(  # ty: ignore[missing-argument]
    sql_server.fully_qualified_domain_name, sql_database.name
).apply(lambda args: _custom_data(*args))  # ty: ignore[invalid-argument-type]

virtual_machine = compute.VirtualMachine(
    "rse-vm",
    resource_group_name=resource_group.name,
    hardware_profile=compute.HardwareProfileArgs(vm_size="Standard_B2s"),
    network_profile=compute.NetworkProfileArgs(
        network_interfaces=[
            compute.NetworkInterfaceReferenceArgs(id=network_interface.id, primary=True)
        ],
    ),
    storage_profile=compute.StorageProfileArgs(
        image_reference=compute.ImageReferenceArgs(
            publisher="Canonical",
            offer="0001-com-ubuntu-server-jammy",
            sku="22_04-lts-gen2",
            version="latest",
        ),
        os_disk=compute.OSDiskArgs(
            create_option=compute.DiskCreateOptionTypes.FROM_IMAGE,
            managed_disk=compute.ManagedDiskParametersArgs(
                storage_account_type=compute.StorageAccountTypes.STANDARD_LRS,
            ),
        ),
    ),
    os_profile=compute.OSProfileArgs(
        computer_name="rse-vm",
        admin_username=admin_username,
        admin_password=vm_admin_password.result,
        custom_data=custom_data,
        linux_configuration=compute.LinuxConfigurationArgs(
            disable_password_authentication=False,
        ),
    ),
)
