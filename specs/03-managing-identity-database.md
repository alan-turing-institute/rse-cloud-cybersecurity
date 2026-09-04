# 03 — Managing Identity: Database Access

A plan for part of the first security-hardening iteration flagged as out of scope in [`01-the-scenario.md`](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario): replacing the VM's database access path (the SQL login password) with **Azure Managed Identity** and Azure AD authentication, so the VM reads/writes to the SQL database without depending on any long-lived secret being generated, exported, or typed in by hand. The SQL admin password keeps existing and keeps being exported — it just stops being the VM's own path in, and remains purely as a management/break-glass credential for a human — see [Secrets and config](#secrets-and-config).

This is the **database half** of the managing-identity iteration. The companion plan, [`02-managing-identity-storage.md`](02-managing-identity-storage.md), covers the storage access path; the two are independent and can be implemented (and deployed) in either order. Both rely on the same VM system-assigned identity — see the note under [Design principles](#design-principles).

This plan covers **identity only**, scoped to the VM's own access to the database. RBAC for human/operator access to the resource group, VNet segmentation, Azure Bastion, NSG narrowing, and SSH-key auth all remain deferred to their own later iterations — see [Out of scope](#out-of-scope-still-deferred) below.

## Why this matters

The current deployment (see [`01-the-scenario.md`](01-the-scenario.md)) has the VM using SQL authentication (`db-admin-username` / a Pulumi-generated `admin_password`) against the Azure SQL Database logical server — a long-lived, server-admin-level credential retrieved by a human with `pulumi stack output --show-secrets` and pasted into VS Code by hand.

This exists as a plaintext-capable secret outside Azure's own identity system — in Pulumi state (encrypted, but still a shared secret) and briefly in a human's clipboard. Managed identity removes the VM's *dependency* on that secret: Azure issues short-lived tokens to the VM's identity, and Azure AD role assignments inside the database scope exactly what that identity can do. The password itself isn't removed from the deployment — it stays available for a human to use directly for management, per [Secrets and config](#secrets-and-config).

## Goal

- The VM authenticates to the SQL database using its **system-assigned managed identity** — no SQL login password.
- Database access is **read/write, scoped to the demo database only** — the VM's identity gets `db_datareader`/`db_datawriter` inside that one database, not server-admin or account-owner capabilities.
- No new secrets are introduced for the VM's own database access path.

## Design principles

- **System-assigned, not user-assigned, managed identity.** The VM is the only resource that needs this identity, its lifecycle should match the VM's exactly (created/destroyed with it), and there's no need to share the identity across multiple resources. A system-assigned identity is the simplest fit; user-assigned would only pay off if a second resource needed the same identity. **This identity is shared infrastructure with [`02-managing-identity-storage.md`](02-managing-identity-storage.md)** — both plans call for the same `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` on the VM resource. Whichever of the two plans is implemented first adds it; if the other has already landed, this step is already done and is a no-op to re-specify.
- **Azure AD authentication, not SQL login — and no admin rights.** Azure SQL Database supports Azure AD (Entra ID) authentication as an alternative to SQL logins. This requires:
  1. An **Azure AD administrator** set on the `sql.Server` (`sql.ServerAzureADAdministrator`) — a prerequisite for any Azure AD auth against the server at all. This is a human/group principal, not the VM.
  2. A **contained database user** created *inside* the one demo database, mapped to the VM's managed identity, and added to the `db_datareader` and `db_datawriter` roles only — read/write on that database's data, nothing else. The VM's identity is never made `db_owner`, never granted server-admin rights, and has no access to any other database on the server. Because a contained database user only exists inside the database it's created in, this scoping is structural, not just a role choice. Creating the user and role membership is SQL DDL (`CREATE USER ... FROM EXTERNAL PROVIDER`), not a Pulumi/ARM resource — see [Database role-membership script](#database-role-membership-script-outside-pulumi) below for how it's applied.
- **The SQL admin login isn't removed — it stops being the VM's path in, and is kept for management.** `administrator_login`/`administrator_login_password` still need to exist on `sql.Server` (Azure SQL Database requires at least one server admin, SQL or Azure AD, at creation). Once the managed-identity path is in place, the VM stops depending on it, but it stays exported as a secret stack output so a human can still manage/troubleshoot the database directly (e.g. running the role-membership script below, or using `sqlcmd` outside the VM) — see [Secrets and config](#secrets-and-config).
- **VS Code extensions move from SQL login to Azure AD auth — `ms-mssql.mssql` has no explicit "Managed Identity" auth type, but "Microsoft Entra ID - Default" is the closest fit.** Researched against the extension's current docs ([Connect to a Database — MSSQL extension](https://learn.microsoft.com/en-us/sql/tools/visual-studio-code-extensions/mssql/mssql-database-connections)): the extension's supported authentication types are SQL Login, Windows Authentication (not available for Azure SQL), **Microsoft Entra ID - Universal with MFA** (interactive human sign-in), **Microsoft Entra ID - Default**, and **Microsoft Entra ID - Service Principal** (client ID + client secret). There's no dedicated "Managed Identity" option:
  - **Microsoft Entra ID - Default** is the one to use. Per the docs, it "automatically selects an available Microsoft Entra ID identity from credential providers installed on your system" — the same `DefaultAzureCredential`-style fallback chain used elsewhere in the Azure SDK, which tries a managed identity (via IMDS) when no other credential provider (a signed-in `az login` session, environment-variable credentials, etc.) is present. Running VS Code on the VM itself, with nothing else signed in, this should resolve to the VM's system-assigned managed identity without any interactive sign-in — but this needs confirming in practice against the extension's actual behavior at implementation time (see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)), since the docs describe the credential chain in general terms rather than guaranteeing managed-identity resolution specifically.
  - **Universal with MFA** is wrong for this — it's built for a human interactively signing in, which is exactly what managed identity is meant to avoid.
  - **Service Principal** is also wrong — it needs a client secret, which would just reintroduce a stored credential; the VM's managed identity doesn't have (or need) one.
  - The pre-created `mssql.connections` profile's `authenticationType` moves from `SqlLogin` to whatever `settings.json` value corresponds to "Microsoft Entra ID - Default" (needs confirming against the extension's schema — see open questions); `user`/`password`/`savePassword` are dropped either way, since there's no password to pre-seed or blank out.
  - **If "Microsoft Entra ID - Default" doesn't reliably pick up the VM's managed identity in practice**, the Microsoft-official fallback is **`sqlcmd` (the [go-sqlcmd](https://github.com/microsoft/go-sqlcmd) build)** with `--authentication-method ActiveDirectoryManagedIdentity` — [officially documented](https://learn.microsoft.com/en-us/sql/tools/sqlcmd/sqlcmd-authentication) and confirmed to work for a system-assigned identity with no extra arguments (a user-assigned identity would need `-U <client-id>`, not needed here). The other two Microsoft SQL client tools that support an explicit "Managed Identity" auth mode don't fit this VM: **SSMS** is Windows-only (this VM is Ubuntu), and **Azure Data Studio** has been retired/folded into the `ms-mssql.mssql` extension, so it's not a separate option any more.
  - **`sqlcmd` (go-sqlcmd) is installed on the VM itself, via cloud-init, so the fallback is available without any extra setup if it's ever needed** — see [Virtual machine](#virtual-machine-infracomputepy) below. This deliberately revises [`01-the-scenario.md`'s "VS Code is the only interface, no CLI tooling" design principle](01-the-scenario.md#design-principles) for **database access specifically**: given the real uncertainty over whether "Microsoft Entra ID - Default" actually resolves the managed identity in the VS Code extension (see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)), having a confirmed-working CLI fallback pre-installed is worth the small deviation from that principle, rather than leaving the operator stuck mid-demo with no way to connect to the database at all.
- **Minimum-cost stays intact.** Managed identity and Azure AD authentication carry no additional Azure cost — this iteration changes the access *mechanism*, not the resource SKUs/tiers from `01-the-scenario.md`.
- **Tests stay mock-based, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).** No `pulumi up`/`pulumi preview` as part of building this — new/changed resources (identity block, AAD administrator) get unit tests via `pulumi.runtime.set_mocks`, same pattern as the existing suite.

## Changes by resource

### Virtual machine (`infra/compute.py`)

- Add `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` to the `compute.VirtualMachine` resource (see the shared-identity note under [Design principles](#design-principles)). Azure provisions a service principal in Entra ID tied to the VM's lifecycle, exposed on the resource as `identity.principal_id`.
- `cloud-init` / the pre-created `mssql.connections` profile (`_vscode_settings_json` in `infra/compute.py`) changes as described above — `authenticationType` switches away from `SqlLogin`, and the `user`/`password`/`savePassword` keys are dropped. The profile still needs `server` and `database`, which are unaffected.
- **New cloud-init step: install `sqlcmd` (go-sqlcmd)**, added to `infra/templates/vm-cloud-init.yaml.j2` alongside the existing VS Code/Chrome install steps — via the [official Microsoft install instructions](https://github.com/microsoft/go-sqlcmd#install) (a downloaded `.deb` package, or the `mssql-tools18`/`go-sqlcmd` apt package, whichever the current Microsoft-documented method is at implementation time). This is the fallback path for database access described under [Design principles](#design-principles) — always present on the VM from first boot, not something the operator has to install ad hoc if VS Code's managed-identity auth doesn't work. No configuration/profile is pre-seeded for it (unlike the mssql VS Code profile) since it's a manual command-line fallback, not the primary path; the operator supplies `-S <server FQDN>`, `-d rse_demo_db`, and `--authentication-method ActiveDirectoryManagedIdentity` by hand when/if they need it.
- No change to `os_profile` (VM login stays password-based — deferred to the SSH-key iteration) and no change to the `ms-azuretools.vscode-azurestorage` attach flow — that's [`02-managing-identity-storage.md`](02-managing-identity-storage.md)'s concern.

### Database access (`infra/database.py`)

- New `sql.ServerAzureADAdministrator` resource, setting an Azure AD principal (a user, group, or service principal — see open question on *which* principal, since this is normally a human/group, not the VM itself) as the server's Azure AD admin. This is what makes Azure AD authentication possible against the server at all; it's a prerequisite, not the VM's own grant.
  - The principal's identifying values (object ID and display name/login) are read from **environment variables**, not Pulumi config: e.g. `AAD_ADMIN_OBJECT_ID` and `AAD_ADMIN_LOGIN`, read via `os.environ[...]` as module-level constants in `infra/database.py` (alongside the existing `config = pulumi.Config()` block, per [`CLAUDE.md`'s module layout guideline](../CLAUDE.md#module-layout-constants-before-functionsclasses)), rather than being written into `Pulumi.dev.yaml`. This keeps the admin identity out of source control and lets it vary per person running `pulumi up`/tests without editing a committed file. See [Secrets and config](#secrets-and-config).
- The VM's managed identity still needs an explicit **database-level** grant — creating a contained user for it and adding that user to `db_datareader`/`db_datawriter` only (no `db_owner`, no server role) — applied via the script described in [Database role-membership script](#database-role-membership-script-outside-pulumi) below, since this is SQL DDL, not something `pulumi_azure_native` can express as a resource.
- `sql.Server`'s `administrator_login`/`administrator_login_password` and the `pulumi_random.RandomPassword` generating it stay in the program (still required at server creation) and **keep being exported** — the VM's runtime access path stops depending on them, but they remain available for management (including running the script below). See [Secrets and config](#secrets-and-config).

### Database role-membership script (outside Pulumi)

The `CREATE USER ... FROM EXTERNAL PROVIDER` / role-membership step can't be expressed as a Pulumi/ARM resource, since it's data inside the database rather than an Azure resource. It's applied via a small script using `sqlcmd`, run manually by a human after `pulumi up` — not by Pulumi, and not by Claude, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).

- New script, e.g. `scripts/grant-vm-db-access.sh`, wrapping `sqlcmd` (the [go-sqlcmd](https://github.com/microsoft/go-sqlcmd) build, needed for Azure AD auth flags) rather than a raw Python/DDL string built up in the Pulumi program.
- Runs against the SQL server FQDN and database name from the stack outputs (`sql_server_fqdn`; the database name is the fixed `rse_demo_db`), authenticating with the SQL admin login/password (`db-admin-username` / the exported `db_admin_password` — see [Secrets and config](#secrets-and-config)), since that's a non-interactive credential a script can use directly, unlike the Azure AD administrator, which is a human/group principal.
- Executes, idempotently (guarded with an `IF NOT EXISTS` check against `sys.database_principals` so the script is safe to re-run):
  ```sql
  IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'rse-vm')
  BEGIN
      CREATE USER [rse-vm] FROM EXTERNAL PROVIDER;
  END
  ALTER ROLE db_datareader ADD MEMBER [rse-vm];
  ALTER ROLE db_datawriter ADD MEMBER [rse-vm];
  ```
  `rse-vm` is the VM's Azure resource/display name (matching `infra/compute.py`'s `compute.VirtualMachine("rse-vm", ...)`), which is how Azure AD resolves the managed identity's login name inside `FROM EXTERNAL PROVIDER`.
- This requires a `sqlcmd` install to run from — either the operator's own machine, or, now that `sqlcmd` is installed on the VM as the [DB-access fallback](#design-principles), from an RDP/SSH session on the VM itself. Either works; the script doesn't care where it's invoked from as long as `sqlcmd` and network access to the SQL server are available.
- Referenced from [Migration / rollout notes](#migration--rollout-notes) as the manual step between `pulumi up` and reconnecting VS Code.

## Obtaining `AAD_ADMIN_OBJECT_ID` and `AAD_ADMIN_LOGIN`

Whoever runs `pulumi up`/`pulumi preview` decides which Azure AD principal (a user or a group — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)) becomes the SQL server's Azure AD admin, then looks up that principal's object ID and login/display name using one of the following.

- **Azure CLI (`az`), for the currently signed-in user** — the simplest case, when the person running `pulumi up` is also meant to be the Azure AD admin:
  ```bash
  export AAD_ADMIN_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
  export AAD_ADMIN_LOGIN=$(az ad signed-in-user show --query userPrincipalName -o tsv)
  ```
- **Azure CLI, for a different user** (by UPN or email):
  ```bash
  export AAD_ADMIN_OBJECT_ID=$(az ad user show --id "someone@example.com" --query id -o tsv)
  export AAD_ADMIN_LOGIN=$(az ad user show --id "someone@example.com" --query userPrincipalName -o tsv)
  ```
- **Azure CLI, for a group** (recommended if the admin should be a team rather than one person, so the assignment survives staff changes):
  ```bash
  export AAD_ADMIN_OBJECT_ID=$(az ad group show --group "My Group Name" --query id -o tsv)
  export AAD_ADMIN_LOGIN=$(az ad group show --group "My Group Name" --query displayName -o tsv)
  ```
- **Azure Portal, as an alternative to the CLI:**
  1. Go to **Microsoft Entra ID** → **Users** (or **Groups**, for a group admin).
  2. Search for and open the target user or group.
  3. On its **Overview** page, copy the **Object ID** field — this is `AAD_ADMIN_OBJECT_ID`.
  4. For a user, copy the **User principal name** field for `AAD_ADMIN_LOGIN`; for a group, copy its **Name**/display name field instead.

Either way, requires `Directory.Read.All`-equivalent read access in Azure AD to look up another user's or a group's details (reading one's own signed-in-user details needs no special permission). These two values are then exported in the shell (or CI environment) before running `pulumi up`/`pulumi preview`/`uv run pytest`, per [Secrets and config](#secrets-and-config).

## Secrets and config

- **`db_admin_password` keeps being exported as a secret stack output**, unchanged from today — it's no longer part of the VM's own access path, but is kept specifically for **management purposes**: an operator running the role-membership script above, or otherwise managing the database directly (e.g. via `sqlcmd`) outside of what the VM's managed identity is scoped to do.
- **No new secrets introduced** for the VM's own database access. Managed identity tokens are issued and rotated by Azure automatically; nothing new is generated by Pulumi or stored in state for that path.
- **The Azure AD administrator's identity is supplied via environment variables, not Pulumi config.** `AAD_ADMIN_OBJECT_ID` (the principal's Azure AD object ID) and `AAD_ADMIN_LOGIN` (its display name/UPN) are read with `os.environ[...]` in `infra/database.py` and passed into `sql.ServerAzureADAdministrator`. Neither value is a secret (an object ID and a display name aren't sensitive), but they're still kept out of `Pulumi.dev.yaml` — whoever runs `pulumi up`/`pulumi preview`/`uv run pytest` sets them in their own shell/CI environment instead, per [Obtaining `AAD_ADMIN_OBJECT_ID` and `AAD_ADMIN_LOGIN`](#obtaining-aad_admin_object_id-and-aad_admin_login) above. Unit tests that exercise `infra/database.py` need these env vars set too (e.g. via `monkeypatch.setenv` in `tests/test_database.py`, or a fixture providing placeholder values), since the module reads them at import/module-evaluation time.

## Testing plan

Extending the existing `pulumi.runtime.set_mocks`-based suite (mirroring the module layout per [`01-the-scenario.md`](01-the-scenario.md#module-layout)):

- `tests/test_compute.py` — assert the VM resource's `identity.type` is `SystemAssigned`; assert the rendered `custom_data` no longer embeds `SqlLogin`/a `user`/`password` key in the `mssql.connections` profile once the profile format changes; assert `custom_data` references the `sqlcmd`/go-sqlcmd install step, so the fallback install isn't silently dropped from the cloud-init template.
- `tests/test_database.py` — assert a `sql.ServerAzureADAdministrator` resource exists on the server with the object ID/login taken from `AAD_ADMIN_OBJECT_ID`/`AAD_ADMIN_LOGIN` (set via `monkeypatch.setenv` for the test, since `infra/database.py` reads them from the environment); assert `db_admin_password`/`administrator_login_password` is still wired into `sql.Server` (kept for management).
- Per [`01-the-scenario.md`'s testing plan](01-the-scenario.md#testing-plan), the earlier scenario's tests deliberately didn't assert on identity/RBAC presence, since that posture was out of scope then — this iteration is where those tests get added, per that document's own note.
- Still no live Azure calls — `MockResourceArgs`/`MockCallArgs`, run via `uv run pytest`, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature). The `scripts/grant-vm-db-access.sh` role-membership script is outside what mocked Pulumi unit tests can cover — it has no automated test in this plan; it's reviewed by reading it, and verified live only by the human running it.

## Migration / rollout notes

- This is not a from-scratch resource — it changes an **existing, potentially-already-deployed** stack. `identity` on an existing VM and a new `ServerAzureADAdministrator` are additive changes Pulumi can apply in place — though the `mssql.connections` profile content inside `custom_data` does change, which **does** force a VM replace under the existing `replace_on_changes=["osProfile.customData"]` policy — worth calling out explicitly to whoever runs the deploy.
- Order of operations for a human running this (not Claude, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature)):
  1. `pulumi up` to create the VM identity and AAD administrator.
  2. Run `scripts/grant-vm-db-access.sh` (see [Database role-membership script](#database-role-membership-script-outside-pulumi)) to create the VM's database user and grant it `db_datareader`/`db_datawriter` — this can't be part of the Pulumi program itself.
  3. Reconnect the mssql VS Code profile using the "Microsoft Entra ID - Default" auth type. If that doesn't pick up the managed identity, fall back to the `sqlcmd` install already on the VM (`sqlcmd -S <server FQDN> -d rse_demo_db --authentication-method ActiveDirectoryManagedIdentity`) — see [Design principles](#design-principles) — to confirm the database path works even while the VS Code auth question is unresolved.
  4. The SQL admin password stays exported and in place throughout — it's kept deliberately, for management, not something to revoke or rotate as part of this rollout.

## Out of scope (still deferred)

Per [`01-the-scenario.md`'s planned follow-up](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario), this iteration is identity/RBAC only. Still deferred to later iterations:

- VNet-integrated / private database access (service endpoints or private link) and removing the `0.0.0.0`–`255.255.255.255` SQL firewall rule.
- Narrowing the NSG's SSH/RDP rules to a trusted IP range instead of `Internet`/`0.0.0.0/0`.
- SSH key authentication on the VM instead of password auth (VM login is unrelated to the resource-access identity work here).
- Azure Bastion or another jump-host pattern instead of a directly internet-facing VM.
- **RBAC for human/operator access to the resource group** (e.g. moving off a subscription-level Owner/Contributor grant to a resource-group-scoped role). This iteration only scopes the VM's own access; who can manage the deployment's Azure resources is not addressed here.
- Storage account access — see [`02-managing-identity-storage.md`](02-managing-identity-storage.md).

## Open questions / assumptions to confirm before implementing

1. **Who, concretely, is the Azure AD administrator on the SQL server?** The *mechanism* is settled — the principal's object ID/login are supplied via the `AAD_ADMIN_OBJECT_ID`/`AAD_ADMIN_LOGIN` environment variables (see [Secrets and config](#secrets-and-config)) — but the actual person or group those values should point to still needs to come from whoever owns the Azure AD tenant for this project. `sql.ServerAzureADAdministrator` needs a real Azure AD principal (a person's account, or a group) — not the VM's own identity, which only needs a *database user*, not server-admin rights.
2. **Does `ms-mssql.mssql`'s "Microsoft Entra ID - Default" auth type actually resolve to the VM's system-assigned managed identity in practice**, and what's the exact `settings.json` `authenticationType` value for it? The extension's docs describe a `DefaultAzureCredential`-style fallback chain in general terms without explicitly guaranteeing managed-identity resolution — this needs a hands-on check once the VM is provisioned with the identity + AAD administrator in place, per [Design principles](#design-principles). `sqlcmd`/`ActiveDirectoryManagedIdentity` is installed on the VM regardless as the confirmed-working fallback, so this question affects whether VS Code stays the operator's primary/only path for the demo, not whether database access works at all.
