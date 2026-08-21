# 01 — The Scenario

A minimum-cost Azure environment, built with the [tech stack](tech-stack.md), consisting of:

1. A **storage account**.
2. An instance of the **cheapest RDBMS product available in Azure**.
3. A **virtual machine** that can read/write blobs in the storage account and run SQL queries against the database.
4. **Unit tests** for the Pulumi program using Pulumi's mocking framework.

## Design principles

- **Minimum cost first.** Every SKU/tier choice below picks the cheapest option that still satisfies the scenario — including the choice of RDBMS itself: **Azure SQL Database, Basic tier (DTU-based)** is the cheapest managed relational database Azure offers (~$5/month), undercutting the cheapest Postgres/MySQL Flexible Server Burstable tier (~$12–15/month compute alone).
- **This is the initial setup — security is deliberately out of scope for now.** No managed identities, no RBAC role assignments, no VNet segmentation, no Azure Bastion. The virtual machine, storage account, and database are all reachable directly over the public internet. The one exception is a minimal NSG on the VM subnet that allows inbound SSH (port 22) from any internet-connected computer — needed simply so the VM is reachable for the demo; it is not a security boundary (it allows SSH from `0.0.0.0/0`) and all other ports remain open via the default allow-all rules. Security hardening (private networking, managed identity, least-privilege RBAC, restricted access, narrowing this NSG to a trusted IP range) is planned as a **later iteration**, not part of this scenario.
- The database uses **SQL authentication (username/password)** — Basic tier's DTU model doesn't change this; it's the standard way to authenticate to it.
- The virtual machine runs **Linux** and also uses **password authentication** (not an SSH key) — SSH key auth is a hardening step deferred to a later iteration along with the rest of the security work.
- Single resource group, single region (config `azure-native:location`, currently `westeurope`), single environment (`dev` stack) — no multi-region or HA requirements for this scenario.

## Estimated cost

Rough order of magnitude, West Europe, pay-as-you-go — enough to sanity-check "minimum cost," not a quote:

| Resource | SKU | ~Monthly cost |
|---|---|---|
| VM | `Standard_B1s` (1 vCPU, 1 GiB, Burstable) | ~$8 |
| VM OS disk | Standard HDD (`Standard_LRS`) managed disk | ~$2 |
| Azure SQL Database | Basic tier (5 DTUs, 2 GB max size) | ~$5 |
| Storage account | `Standard_LRS`, `StorageV2`, negligible usage | ~$1–2 |
| Public IP (VM) | Standard SKU, static (Basic SKU is retired) | ~$3–4 |
| **Total** | | **~$20/month** |

Switching the database from PostgreSQL Flexible Server (Burstable `B1ms`, ~$25–30/month) to Azure SQL Database Basic tier (~$5/month) is what drives most of the savings versus the previous iteration of this plan — Basic tier has no materially cheaper alternative for a managed RDBMS on Azure. If cost needs to drop further, the main remaining lever is turning the stack off with `pulumi destroy` between demos.

## Resource inventory

All resources go in the existing `rse-cloud-cybersecurity-rg` resource group. Class names/import paths below are from `pulumi_azure_native` (verified against the installed SDK), Python.

### Networking

Azure VMs must sit in a VNet/subnet regardless of security posture, so a minimal VNet is still needed purely as a platform requirement. SSH connectivity to the VM currently doesn't work, so a minimal NSG is attached to the VM subnet allowing inbound SSH from anywhere — it is not meant as a security boundary, just enough to make the VM reachable; every other port is still open via the default allow-all rules.

| Resource | Class | Notes |
|---|---|---|
| Virtual network | `network.VirtualNetwork` | One VNet, address space e.g. `10.0.0.0/16`. |
| Network security group | `network.NetworkSecurityGroup` | One inbound rule: allow TCP port 22 (SSH) from source `Internet` (or `*`/`0.0.0.0/0`), priority e.g. `100`, `access=Allow`, `direction=Inbound`. No other rules — everything else falls through to the default allow-all rules, so this does not otherwise restrict traffic. |
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
- `hardware_profile=compute.HardwareProfileArgs(vm_size="Standard_B1s")`
- **Linux** (Ubuntu LTS) image reference — no Windows licensing cost.
- OS disk: `compute.OSDiskArgs(managed_disk=compute.ManagedDiskParametersArgs(storage_account_type="Standard_LRS"), create_option="FromImage")`.
- `network_profile` referencing the NIC above (public IP attached, no NSG — SSH and any other port are reachable from the internet).
- No `identity` block — no managed identity at this stage.
- `os_profile` uses **password authentication**: `admin_username` + a Pulumi-generated `admin_password` (via `pulumi_random.RandomPassword`, exported as a secret stack output — see below), with `linux_configuration.disable_password_authentication=False`. No SSH key is configured at this stage — that's part of the later security hardening iteration.
- `os_profile.custom_data` — base64-encoded cloud-init that installs the Azure CLI (for blob access using the storage account key/connection string, exported as a stack output — see below) and Microsoft's `sqlcmd` CLI (`mssql-tools18`, from Microsoft's package repository) for running SQL queries against the database.

No RBAC / role assignment resource is created at this stage. The VM authenticates to storage using the storage account connection string/key (exported as a secret stack output), and to the database using the admin password (also a secret stack output) — both handed to the operator running the demo rather than baked into the VM automatically.

## Secrets and config

- `administrator_login_password` for the SQL Server logical server: generate with `pulumi.random.RandomPassword` (or equivalent), mark as a Pulumi secret, pass into `sql.Server`. Export it as a **secret** stack output so a human doing the demo can retrieve it via `pulumi stack output --show-secrets`, rather than baking it into config or a script.
- VM `admin_password`: generate with `pulumi.random.RandomPassword` the same way, pass into `os_profile.admin_password`, and export as a **secret** stack output — this is how the operator logs into the VM, since no SSH key is configured at this stage.
- Storage account connection string/key: export the primary key or full connection string as a **secret** stack output the same way, for manual use on the VM (e.g. `az storage blob` commands, or an environment variable set by hand).
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
- One test per resource asserting its URN/type token and key inputs land as expected for the **functional/cost** requirements this scenario states (e.g. storage account SKU is `Standard_LRS`, SQL Database SKU tier is `Basic`, VM size is `Standard_B1s`, VM uses a Linux OS profile with password authentication enabled).
- **Do not** assert on the presence/absence of security measures at this stage (e.g. whether a managed identity is attached, whether a resource is VNet-integrated, whether an NSG exists or what it allows). Those postures are deliberately permissive right now and are revisited in the later security-hardening iteration (see below) — pinning them down in tests now would just make that later work fail tests that were never meant to encode a security requirement. Tests for those measures are added when the corresponding hardening work lands.
- Keep using `MockResourceArgs`/`MockCallArgs` mocks — no real Azure credentials or calls needed to run `uv run pytest`.

## Open questions / assumptions to confirm before implementing

1. **Region**: keeping `westeurope` (already configured) unless the presentation needs a different one.
2. **Basic Public IP SKU retirement**: plan assumes Standard SKU + static allocation is required (Basic retired). Worth a final live check against Azure's current SKU support at implementation time.

## Planned follow-up (later iteration, not part of this scenario)

- Re-introduce a VNet-integrated, private database (e.g. via Azure SQL Database's VNet service endpoints/private link, or a private-access-capable engine); a subnet-scoped NSG restricting SSH to a trusted IP; SSH key authentication on the VM instead of a password; a system-assigned managed identity on the VM with a scoped RBAC role assignment for storage access instead of account keys; and consider Azure Bastion (or another jump-host pattern) instead of a directly internet-facing VM.
- Add unit tests for the security measures introduced in that iteration (managed identity presence, VNet integration, NSG rules, etc.) — deliberately not covered by this scenario's tests.
