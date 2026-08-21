# 01 — The Scenario

A minimum-cost Azure environment, built with the [tech stack](tech-stack.md), consisting of:

1. A **storage account**.
2. An instance of the **cheapest RDBMS product available in Azure**.
3. A **virtual machine**, with a graphical desktop environment reachable over **RDP**, that comes with software pre-installed to (a) download data from the storage account and (b) run queries against the database. **VS Code** comes pre-installed and pre-configured as the expected way for the operator to do both — connecting to the storage account and to the SQL database from inside the editor, ready to use without further setup.
4. **Unit tests** for the Pulumi program using Pulumi's mocking framework.

## Design principles

- **Minimum cost first.** Every SKU/tier choice below picks the cheapest option that still satisfies the scenario — including the choice of RDBMS itself: **Azure SQL Database, Basic tier (DTU-based)** is the cheapest managed relational database Azure offers (~$5/month), undercutting the cheapest Postgres/MySQL Flexible Server Burstable tier (~$12–15/month compute alone).
- **This is the initial setup — security is deliberately out of scope for now.** No managed identities, no RBAC role assignments, no VNet segmentation, no Azure Bastion. The virtual machine, storage account, and database are all reachable directly over the public internet. The one exception is a minimal NSG on the VM subnet that allows inbound SSH (port 22) from any internet-connected computer — needed simply so the VM is reachable for the demo; it is not a security boundary (it allows SSH from `0.0.0.0/0`) and all other ports remain open via the default allow-all rules. Security hardening (private networking, managed identity, least-privilege RBAC, restricted access, narrowing this NSG to a trusted IP range) is planned as a **later iteration**, not part of this scenario.
- The database uses **SQL authentication (username/password)** — Basic tier's DTU model doesn't change this; it's the standard way to authenticate to it.
- The virtual machine runs **Linux** and also uses **password authentication** (not an SSH key) — SSH key auth is a hardening step deferred to a later iteration along with the rest of the security work.
- The VM needs a **graphical desktop reachable over RDP**. To keep this on the cheapest possible SKU, it stays the same Ubuntu VM rather than switching to (or adding) a Windows VM — a lightweight desktop environment (XFCE) plus `xrdp` gives an RDP-reachable GUI on Linux without incurring Windows Server licensing costs. RDP logs in with the same Linux admin username/password already provisioned for SSH — no separate credential.
- The VM's CLI software (Azure CLI for blob access, `sqlcmd` for database queries) is installed the same way whether accessed via SSH or via a terminal inside the graphical desktop — the GUI doesn't change how those tools are invoked, just how the VM is reached. These stay installed as a terminal-based fallback, but **VS Code is the expected primary interface**: the operator connects to the storage account and the database from inside the editor rather than typing CLI commands.
- VS Code is pre-installed with two extensions, pre-configured as far as each extension's own documented mechanism actually allows — **not** a full zero-touch connection for either, since neither extension has a supported way to pre-seed a password/connection string outside of that mechanism:
  - **`ms-mssql.mssql`** (SQL Server / Azure SQL extension) — a connection profile (server FQDN, database, username, `authenticationType: SqlLogin`) is pre-created in `settings.json` under `mssql.connections`. The password is deliberately left blank with `savePassword: true`: this extension never stores passwords in `settings.json` (documented behavior — they go into VS Code's secure credential store, `~/.sqlsecrets/sqlsecrets.json` on Linux), so the operator enters it once, using the value from the secret stack output, and it's remembered from then on.
  - **`ms-azuretools.vscode-azurestorage`** (Azure Storage extension) — only the extension itself is pre-installed. There's no documented `settings.json` key for pre-attaching a storage account; attaching one (by connection string, via the extension's "Attach Storage Account..." command, no Azure AD sign-in needed) is a one-time manual step the operator does using the connection string from the secret stack output.
- Pre-creating the mssql connection profile bakes non-secret connection details (server, database, username) into a file on the VM — a minor exposure, consistent with this scenario's "no security yet" stance, but the SQL password and the storage connection string are **not** written to the VM's disk; they only ever reach the VM as something the operator types in/pastes in by hand.
- Single resource group, single region (config `azure-native:location`, currently `westeurope`), single environment (`dev` stack) — no multi-region or HA requirements for this scenario.

## Estimated cost

Rough order of magnitude, West Europe, pay-as-you-go — enough to sanity-check "minimum cost," not a quote:

| Resource | SKU | ~Monthly cost |
|---|---|---|
| VM | `Standard_B2s` (2 vCPU, 4 GiB, Burstable) | ~$30 |
| VM OS disk | Standard HDD (`Standard_LRS`) managed disk | ~$2 |
| Azure SQL Database | Basic tier (5 DTUs, 2 GB max size) | ~$5 |
| Storage account | `Standard_LRS`, `StorageV2`, negligible usage | ~$1–2 |
| Public IP (VM) | Standard SKU, static (Basic SKU is retired) | ~$3–4 |
| **Total** | | **~$42/month** |

Switching the database from PostgreSQL Flexible Server (Burstable `B1ms`, ~$25–30/month) to Azure SQL Database Basic tier (~$5/month) is what drives most of the savings versus the previous iteration of this plan — Basic tier has no materially cheaper alternative for a managed RDBMS on Azure. The VM size has moved twice since then: `Standard_B1s` (1 GiB RAM) → `Standard_B1ms` (2 GiB RAM) to give the desktop environment + `xrdp` room to run, then → `Standard_B2s` (2 vCPU, 4 GiB RAM) to give VS Code (an Electron app) enough headroom on top of the desktop session — VS Code plus a couple of extensions is unlikely to run comfortably in 2 GiB alongside XFCE. `B2s` is the cheapest Burstable size with 4 GiB and still avoids Windows licensing. If cost needs to drop further, the main remaining lever is turning the stack off with `pulumi destroy` between demos.

## Resource inventory

All resources go in the existing `rse-cloud-cybersecurity-rg` resource group. Class names/import paths below are from `pulumi_azure_native` (verified against the installed SDK), Python.

### Networking

Azure VMs must sit in a VNet/subnet regardless of security posture, so a minimal VNet is still needed purely as a platform requirement. SSH connectivity to the VM currently doesn't work, so a minimal NSG is attached to the VM subnet allowing inbound SSH from anywhere; the same NSG also needs an RDP rule so the new graphical desktop is reachable — neither rule is meant as a security boundary, just enough to make the VM reachable; every other port is still open via the default allow-all rules.

| Resource | Class | Notes |
|---|---|---|
| Virtual network | `network.VirtualNetwork` | One VNet, address space e.g. `10.0.0.0/16`. |
| Network security group | `network.NetworkSecurityGroup` | Two inbound rules: allow TCP port 22 (SSH) and allow TCP port 3389 (RDP), both from source `Internet` (or `*`/`0.0.0.0/0`), distinct priorities e.g. `100`/`110`, `access=Allow`, `direction=Inbound`. No other rules — everything else falls through to the default allow-all rules, so this does not otherwise restrict traffic. |
| VM subnet | `network.Subnet` | e.g. `10.0.1.0/24`. `network_security_group` set to the NSG above. |
| Public IP | `network.PublicIPAddress` | `sku=PublicIPAddressSkuArgs(name=PublicIPAddressSkuName.STANDARD)`, `public_ip_allocation_method=IPAllocationMethod.STATIC` (Standard SKU requires static; Basic SKU is retired). |
| NIC | `network.NetworkInterface` | Attaches the VM subnet + public IP. |

The database does **not** use this VNet — see below, it gets its own public endpoint.

### Storage account

`storage.StorageAccount`:
- `kind=storage.Kind.STORAGE_V2`
- `sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS)`
- `location`, `resource_group_name` from the existing resource group.
- Default network rules (public network access enabled, no firewall/VNet rule restrictions) — reachable over the public internet.
- Consider `access_tier=storage.AccessTier.HOT` (default) — fine for light demo usage; no lifecycle policy needed at this scale.
- A single blob container (`storage.BlobContainer`) for the VM to read/write against.

### Database (Azure SQL Database, Basic tier)

Azure SQL Database is a two-resource model: a logical **server** (the administrative/auth boundary and public endpoint) plus one or more **databases** on it.

`sql.Server` (the logical server):
- `administrator_login` + a Pulumi-generated `administrator_login_password` (see [Secrets](#secrets-and-config) below) — SQL authentication.
- `version="12.0"` (the current/only version token for Azure SQL Database logical servers).
- No `identity` block, default `public_network_access` (public) — reachable from the internet.

`sql.Database` (the working database):
- `sku=sql.SkuArgs(name="Basic", tier="Basic")` — the cheapest tier.
- `server_name` referencing the server above.

`sql.FirewallRule` allowing the full public range (`start_ip_address="0.0.0.0"`, `end_ip_address="255.255.255.255"`) so the server is reachable from anywhere, consistent with "no security yet."

### Virtual machine

`compute.VirtualMachine`:
- `hardware_profile=compute.HardwareProfileArgs(vm_size="Standard_B2s")` — bumped from `Standard_B1ms` to `Standard_B2s` (2 vCPU, 4 GiB) so VS Code has enough headroom on top of the desktop environment + `xrdp`; still Burstable, still no Windows licensing.
- **Linux** (Ubuntu LTS) image reference — no Windows licensing cost.
- OS disk: `compute.OSDiskArgs(managed_disk=compute.ManagedDiskParametersArgs(storage_account_type="Standard_LRS"), create_option="FromImage")`.
- `network_profile` referencing the NIC above (public IP attached; the NSG on the subnet allows both SSH and RDP from the internet, everything else is unfiltered).
- No `identity` block — no managed identity at this stage.
- `os_profile` uses **password authentication**: `admin_username` + a Pulumi-generated `admin_password` (via `pulumi_random.RandomPassword`, exported as a secret stack output — see below), with `linux_configuration.disable_password_authentication=False`. No SSH key is configured at this stage — that's part of the later security hardening iteration. The same username/password is used to log in over RDP, since `xrdp` authenticates against the VM's local Linux accounts by default — no separate RDP credential is generated.
- `os_profile.custom_data` — base64-encoded cloud-init that installs:
  - A lightweight desktop environment (`xfce4`, the standard lightweight choice for `xrdp` on Ubuntu) and `xrdp` itself, enabled and started as a service, giving a graphical desktop reachable over RDP on port 3389 (opened by the NSG rule above).
  - The **Azure CLI** — for downloading/uploading blobs from the storage account (`az storage blob download`/`upload`, using the storage account key/connection string exported as a stack output — see below). Usable from a terminal inside the graphical desktop or over SSH, as a fallback to the VS Code path below.
  - Microsoft's **`sqlcmd`** CLI (`mssql-tools18`, from Microsoft's package repository) — for running SQL queries against the database. Same fallback role as the Azure CLI above.
  - **VS Code** (Microsoft's official `apt` repository, the same pattern already used for `sqlcmd` — add the Microsoft signing key + repo, then `apt-get install code`) plus its `ms-mssql.mssql` and `ms-azuretools.vscode-azurestorage` extensions (`code --install-extension <id>`), installed non-interactively as part of the same cloud-init run.
  - A pre-created VS Code connection profile for `ms-mssql.mssql` — server (the SQL Server logical server's fully-qualified name), database, admin username, with the password left blank and `savePassword: true` (see [Design principles](#design-principles) for why). The server FQDN and database name come from resources created earlier in the same Pulumi program, so `custom_data` is built from `Output.all(...).apply(...)` over those two values, rather than the static string used for the rest of cloud-init — this is the one piece of `custom_data` that can't be known until deploy time. Nothing is pre-configured for `ms-azuretools.vscode-azurestorage` — it's just installed; attaching the storage account is a manual, one-time step for the operator.

No RBAC / role assignment resource is created at this stage. The VM authenticates to storage using the storage account connection string/key, and to the database using the admin password — both are exported as secret stack outputs and handed to the operator to enter by hand (once, for the database, into the pre-created but password-less mssql profile; once, for storage, into the extension's "Attach Storage Account..." command). Neither secret is written to the VM's disk by Pulumi.

## Secrets and config

- `administrator_login_password` for the SQL Server logical server: generate with `pulumi.random.RandomPassword` (or equivalent), mark as a Pulumi secret, pass into `sql.Server`. Export it as a **secret** stack output so a human doing the demo can retrieve it via `pulumi stack output --show-secrets`, rather than baking it into config or a script. This password is deliberately **not** passed into `custom_data` — the `ms-mssql.mssql` extension only ever stores passwords in its own secure credential store, never in `settings.json`, so the operator enters it once (from the stack output) when first connecting via the pre-created profile.
- VM `admin_password`: generate with `pulumi.random.RandomPassword` the same way, pass into `os_profile.admin_password`, and export as a **secret** stack output — this is how the operator logs into the VM (and over RDP), since no SSH key is configured at this stage.
- Storage account connection string/key: export the primary key or full connection string as a **secret** stack output the same way, for manual use on the VM (e.g. `az storage blob` commands, or pasted into the Azure Storage VS Code extension's "Attach Storage Account..." command).
- New Pulumi config values needed in `Pulumi.dev.yaml` (in addition to the existing `azure-native:location`):
  - `db-admin-username` — SQL Server admin login name (non-secret).
  - `vm-admin-username` — VM admin login name (non-secret); the matching password is generated by Pulumi, not supplied via config.

## Module layout

Split `infra.py` into an `infra` package with one module per concern, re-exported so `__main__.py` and the tests keep a single import surface:

- `infra/__init__.py` — re-exports the resource group plus everything from the modules below, so `from infra import resource_group, storage_account, sql_server, virtual_machine, ...` keeps working.
- `infra/networking.py` — VNet, subnet, public IP, NIC.
- `infra/storage.py` — storage account, blob container.
- `infra/database.py` — Azure SQL Database logical server, firewall rule, database.
- `infra/compute.py` — the virtual machine.

`infra.py` (the existing resource-group definition) becomes `infra/__init__.py`'s resource-group section, or a small `infra/resource_group.py` module re-exported the same way — either is fine, the key point is a package with a clear per-concern split instead of one flat file.

## Testing plan

Split `tests/test_infra.py` to mirror the module layout (e.g. `tests/test_networking.py`, `tests/test_storage.py`, `tests/test_database.py`, `tests/test_compute.py`), all using the same `pulumi.runtime.Mocks` + `pulumi.runtime.test` pattern already in place:
- One test per resource asserting its URN/type token and key inputs land as expected for the **functional/cost** requirements this scenario states (e.g. storage account SKU is `Standard_LRS`, SQL Database SKU tier is `Basic`, VM size is `Standard_B2s`, VM uses a Linux OS profile with password authentication enabled).
- The NSG's SSH rule (already tested) and the new RDP rule (port 3389) are both **functional** requirements — the scenario explicitly asks for RDP access — so both are asserted the same way (rule exists, correct port/protocol/direction/access), unlike the security-posture exclusions below.
- `custom_data` (the cloud-init payload) is asserted to reference `xrdp`, the desktop package, the VS Code install step, and both extension IDs (`ms-mssql.mssql`, `ms-azuretools.vscode-azurestorage`) — so none of these functional requirements is silently dropped — without pinning down the exact package manager invocation, which is an implementation detail. The pre-created `mssql.connections` profile embedded in it is checked for `authenticationType: SqlLogin`, the right username, an **empty** password, and `savePassword: true` — pinning down that the password is deliberately absent is as important as pinning down the profile's presence. Because `custom_data` now depends on `Output`s (SQL server FQDN, database name), the test resolves it via `pulumi.Output.all(...).apply(...)` like the other Output-typed properties already tested elsewhere, rather than reading it as a plain string.
- **Do not** assert on the presence/absence of security measures at this stage (e.g. whether a managed identity is attached, whether a resource is VNet-integrated, or whether the NSG's rules are scoped to anything narrower than the whole internet). Those postures are deliberately permissive right now and are revisited in the later security-hardening iteration (see below) — pinning them down in tests now would just make that later work fail tests that were never meant to encode a security requirement. Tests for those measures are added when the corresponding hardening work lands. This is distinct from asserting that the SSH/RDP rules *exist and allow access* (previous bullet) — that's a functional requirement of this scenario, not a security posture.
- Keep using `MockResourceArgs`/`MockCallArgs` mocks — no real Azure credentials or calls needed to run `uv run pytest`.

## Open questions / assumptions to confirm before implementing

1. **Region**: keeping `westeurope` (already configured) unless the presentation needs a different one.
2. **Basic Public IP SKU retirement**: plan assumes Standard SKU + static allocation is required (Basic retired). Worth a final live check against Azure's current SKU support at implementation time.

## Planned follow-up (later iteration, not part of this scenario)

- Re-introduce a VNet-integrated, private database (e.g. via Azure SQL Database's VNet service endpoints/private link, or a private-access-capable engine); a subnet-scoped NSG restricting SSH and RDP to a trusted IP; SSH key authentication on the VM instead of a password; a system-assigned managed identity on the VM with a scoped RBAC role assignment for storage access instead of account keys; and consider Azure Bastion (or another jump-host pattern) instead of a directly internet-facing VM with RDP/SSH open to the world.
- Once a managed identity + RBAC exist, reconfigure the VS Code extensions to use Azure AD sign-in / managed identity for both the database and storage connections, instead of the SQL-login profile and manual connection-string entry used here.
- Add unit tests for the security measures introduced in that iteration (managed identity presence, VNet integration, NSG rules, etc.) — deliberately not covered by this scenario's tests.
