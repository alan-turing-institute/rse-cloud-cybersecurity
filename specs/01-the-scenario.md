# 01 — The Scenario

A minimum-cost Azure environment, built with the [tech stack](tech-stack.md), consisting of:

1. A **storage account**.
2. An **Azure Database for PostgreSQL** instance.
3. A **virtual machine** that can read/write blobs in the storage account and run SQL queries against the PostgreSQL database.
4. **Unit tests** for the Pulumi program using Pulumi's mocking framework.

## Design principles

- **Minimum cost first.** Every SKU/tier choice below picks the cheapest option that still satisfies the scenario.
- **This is the initial setup — security is deliberately out of scope for now.** No managed identities, no RBAC role assignments, no VNet, no NSG, no Azure Bastion. The virtual machine, storage account, and PostgreSQL database are all reachable directly over the public internet. Security hardening (private networking, managed identity, least-privilege RBAC, restricted access) is planned as a **later iteration**, not part of this scenario.
- PostgreSQL uses **password authentication**.
- The virtual machine runs **Linux** and also uses **password authentication** (not an SSH key) — SSH key auth is a hardening step deferred to a later iteration along with the rest of the security work.
- Single resource group, single region (config `azure-native:location`, currently `westeurope`), single environment (`dev` stack) — no multi-region or HA requirements for this scenario.

## Estimated cost

Rough order of magnitude, West Europe, pay-as-you-go — enough to sanity-check "minimum cost," not a quote:

| Resource | SKU | ~Monthly cost |
|---|---|---|
| VM | `Standard_B1s` (1 vCPU, 1 GiB, Burstable) | ~$8 |
| VM OS disk | Standard HDD (`Standard_LRS`) managed disk | ~$2 |
| PostgreSQL Flexible Server | `Standard_B1ms` (Burstable), 32 GB storage | ~$25–30 |
| Storage account | `Standard_LRS`, `StorageV2`, negligible usage | ~$1–2 |
| Public IP (VM) | Standard SKU, static (Basic SKU is retired) | ~$3–4 |
| **Total** | | **~$40–45/month** |

The dominant cost is the PostgreSQL compute tier — there isn't a materially cheaper managed Postgres option on Azure below Burstable `B1ms`. If cost needs to drop further, the two levers are: turning the stack off with `pulumi destroy` between demos, or dropping PostgreSQL storage to the 32 GB minimum (already assumed above).

## Resource inventory

All resources go in the existing `rse-cloud-cybersecurity-rg` resource group. Class names/import paths below are from `pulumi_azure_native` (verified against the installed SDK), Python.

### Networking

Azure VMs must sit in a VNet/subnet regardless of security posture, so a minimal VNet is still needed purely as a platform requirement — no NSG is attached, so nothing is filtered.

| Resource | Class | Notes |
|---|---|---|
| Virtual network | `network.VirtualNetwork` | One VNet, address space e.g. `10.0.0.0/16`. |
| VM subnet | `network.Subnet` | e.g. `10.0.1.0/24`. No NSG attached — all inbound/outbound traffic is allowed. |
| Public IP | `network.PublicIPAddress` | `sku=PublicIPAddressSkuArgs(name=PublicIPAddressSkuName.STANDARD)`, `public_ip_allocation_method=IPAllocationMethod.STATIC` (Standard SKU requires static; Basic SKU is retired). |
| NIC | `network.NetworkInterface` | Attaches the VM subnet + public IP. No NSG. |

PostgreSQL does **not** use this VNet — see below, it gets its own public endpoint.

### Storage account

`storage.StorageAccount`:
- `kind=storage.Kind.STORAGE_V2`
- `sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS)`
- `location`, `resource_group_name` from the existing resource group.
- Default network rules (public network access enabled, no firewall/VNet rule restrictions) — reachable over the public internet.
- Consider `access_tier=storage.AccessTier.HOT` (default) — fine for light demo usage; no lifecycle policy needed at this scale.
- A single blob container (`storage.BlobContainer`) for the VM to read/write against.

### PostgreSQL (Flexible Server)

`dbforpostgresql.Server`:
- `sku=dbforpostgresql.SkuArgs(name="Standard_B1ms", tier=dbforpostgresql.SkuTier.BURSTABLE)`
- `storage=dbforpostgresql.StorageArgs(storage_size_gb=32)` (minimum)
- `version="17"`
- `backup=dbforpostgresql.BackupArgs(backup_retention_days=7, geo_redundant_backup="Disabled")` (7 days is already the minimum/default)
- No `network` args — leaving this unset keeps the server in **public access mode** rather than VNet-integrated, which is what makes it reachable from the internet.
- `auth_config=dbforpostgresql.AuthConfigArgs(password_auth="Enabled")` (or simply rely on the default, which is password auth) plus `administrator_login` + a Pulumi-generated `administrator_login_password` (see [Secrets](#secrets-and-config) below).
- `network.FirewallRule` (`dbforpostgresql.FirewallRule`) allowing the full public range (`start_ip_address="0.0.0.0"`, `end_ip_address="255.255.255.255"`) so the server is reachable from anywhere, consistent with "no security yet."
- One `dbforpostgresql.Database` for the working database used by the demo queries.

### Virtual machine

`compute.VirtualMachine`:
- `hardware_profile=compute.HardwareProfileArgs(vm_size="Standard_B1s")`
- **Linux** (Ubuntu LTS) image reference — no Windows licensing cost.
- OS disk: `compute.OSDiskArgs(managed_disk=compute.ManagedDiskParametersArgs(storage_account_type="Standard_LRS"), create_option="FromImage")`.
- `network_profile` referencing the NIC above (public IP attached, no NSG — SSH and any other port are reachable from the internet).
- No `identity` block — no managed identity at this stage.
- `os_profile` uses **password authentication**: `admin_username` + a Pulumi-generated `admin_password` (via `pulumi_random.RandomPassword`, exported as a secret stack output — see below), with `linux_configuration.disable_password_authentication=False`. No SSH key is configured at this stage — that's part of the later security hardening iteration.
- `os_profile.custom_data` — base64-encoded cloud-init that installs `postgresql-client` (for `psql`) and the Azure CLI (for blob access using the storage account key/connection string, exported as a stack output — see below).

No RBAC / role assignment resource is created at this stage. The VM authenticates to storage using the storage account connection string/key (exported as a secret stack output), and to PostgreSQL using the admin password (also a secret stack output) — both handed to the operator running the demo rather than baked into the VM automatically.

## Secrets and config

- `administrator_login_password` for Postgres: generate with `pulumi.random.RandomPassword` (or equivalent), mark as a Pulumi secret, pass into `dbforpostgresql.Server`. Export it as a **secret** stack output so a human doing the demo can retrieve it via `pulumi stack output --show-secrets`, rather than baking it into config or a script.
- VM `admin_password`: generate with `pulumi.random.RandomPassword` the same way, pass into `os_profile.admin_password`, and export as a **secret** stack output — this is how the operator logs into the VM, since no SSH key is configured at this stage.
- Storage account connection string/key: export the primary key or full connection string as a **secret** stack output the same way, for manual use on the VM (e.g. `az storage blob` commands, or an environment variable set by hand).
- New Pulumi config values needed in `Pulumi.dev.yaml` (in addition to the existing `azure-native:location`):
  - `db-admin-username` — Postgres admin login name (non-secret).
  - `vm-admin-username` — VM admin login name (non-secret); the matching password is generated by Pulumi, not supplied via config.

## Module layout

Split `infra.py` into an `infra` package with one module per concern, re-exported so `__main__.py` and the tests keep a single import surface:

- `infra/__init__.py` — re-exports the resource group plus everything from the modules below, so `from infra import resource_group, storage_account, postgres_server, virtual_machine, ...` keeps working.
- `infra/networking.py` — VNet, subnet, public IP, NIC.
- `infra/storage.py` — storage account, blob container.
- `infra/database.py` — PostgreSQL Flexible Server, firewall rule, database.
- `infra/compute.py` — the virtual machine.

`infra.py` (the existing resource-group definition) becomes `infra/__init__.py`'s resource-group section, or a small `infra/resource_group.py` module re-exported the same way — either is fine, the key point is a package with a clear per-concern split instead of one flat file.

## Testing plan

Split `tests/test_infra.py` to mirror the module layout (e.g. `tests/test_networking.py`, `tests/test_storage.py`, `tests/test_database.py`, `tests/test_compute.py`), all using the same `pulumi.runtime.Mocks` + `pulumi.runtime.test` pattern already in place:
- One test per resource asserting its URN/type token and key inputs land as expected (e.g. storage account SKU is `Standard_LRS`, Postgres SKU tier is `Burstable`, VM uses a Linux OS profile with password authentication enabled).
- A test asserting the Postgres firewall rule opens the full public range (documenting the current "no security yet" posture, so a later iteration that tightens it changes an intentional, visible test rather than something incidental).
- Keep using `MockResourceArgs`/`MockCallArgs` mocks — no real Azure credentials or calls needed to run `uv run pytest`.

## Open questions / assumptions to confirm before implementing

1. **Region**: keeping `westeurope` (already configured) unless the presentation needs a different one.
2. **Basic Public IP SKU retirement**: plan assumes Standard SKU + static allocation is required (Basic retired). Worth a final live check against Azure's current SKU support at implementation time.

## Planned follow-up (later iteration, not part of this scenario)

- Re-introduce a VNet-integrated, private PostgreSQL server; a subnet-scoped NSG restricting SSH to a trusted IP; SSH key authentication on the VM instead of a password; a system-assigned managed identity on the VM with a scoped RBAC role assignment for storage access instead of account keys; and consider Azure Bastion (or another jump-host pattern) instead of a directly internet-facing VM.
