# 01 — Managing Identity

A plan for the first security-hardening iteration flagged as out of scope in [`01-the-scenario.md`](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario): replacing the credential-based access paths (SQL login password, storage account key) with **Azure Managed Identity** and role-based access control (RBAC), so the VM authenticates to the storage account and the SQL database without any long-lived secret being generated, exported, or typed in by hand.

RBAC does double duty in this plan: it's the mechanism that scopes what the VM's managed identity can do (least-privilege data-plane access, [above](#design-principles)), and it's also used on its own, independent of managed identity, to tighten who can manage the deployment's resources at the Azure control-plane (management-plane) level — see [RBAC for human/operator access](#rbac-for-humanoperator-access) below.

This plan covers **identity only**. VNet segmentation, Azure Bastion, NSG narrowing, and SSH-key auth remain deferred to their own later iteration — see [Out of scope](#out-of-scope-still-deferred) below.

## Why this matters

The current deployment (see [`01-the-scenario.md`](01-the-scenario.md)) has two credential-based access paths, both of which end up as secret stack outputs a human retrieves with `pulumi stack output --show-secrets` and pastes into VS Code by hand:

1. **Storage access** — the VM uses the storage account's primary access key (a static, all-or-nothing credential with full control over every container/blob in the account, exported via `pulumi.Output.secret(storage_account_keys.keys[0].value)` in `__main__.py`).
2. **Database access** — the VM uses SQL authentication (`db-admin-username` / a Pulumi-generated `admin_password`) against the Azure SQL Database logical server.

Both are long-lived, both grant broad access (account-level key, server-admin login), and both exist as plaintext-capable secrets somewhere outside Azure's own identity system — in Pulumi state (encrypted, but still a shared secret) and briefly in a human's clipboard. Managed identity removes the secret entirely: Azure issues short-lived tokens to the VM's identity, and RBAC/Azure AD role assignments scope exactly what that identity can do.

## Goal

- The VM authenticates to the storage account and to the SQL database using its **system-assigned managed identity** — no API key, no SQL login password, for either path.
- Access is scoped with **least-privilege RBAC** (storage) and a **least-privilege database role** (SQL), not full account/server control.
- **Human/operator access to the resource group is also scoped with least-privilege RBAC**, not left as default subscription-level Owner/Contributor access — see [RBAC for human/operator access](#rbac-for-humanoperator-access). This is independent of the managed-identity work above: it's about who can manage the deployment's Azure resources, not what the VM itself can do.
- No new secrets are introduced. The `vm_admin_password` (RDP/SSH login) is unaffected by this iteration — it's VM login, not resource access, and is covered by the separate SSH-key hardening iteration.

## Design principles

- **System-assigned, not user-assigned, managed identity.** The VM is the only resource that needs this identity, its lifecycle should match the VM's exactly (created/destroyed with it), and there's no need to share the identity across multiple resources. A system-assigned identity is the simplest fit; user-assigned would only pay off if a second resource needed the same identity.
- **Storage: RBAC role assignment, not a key.** `storage.StorageAccount` keeps existing — only the *access path* changes. The VM's managed identity gets a `authorization.RoleAssignment` scoped to the storage account (or, tighter still, the blob container) with the **Storage Blob Data Contributor** role — read/write on blob data, not account management, not key access.
- **Database: Azure AD authentication, not SQL login.** Azure SQL Database supports Azure AD (Entra ID) authentication as an alternative to SQL logins. This requires:
  1. An **Azure AD administrator** set on the `sql.Server` (`sql.ServerAzureADAdministrator`) — a prerequisite for any Azure AD auth against the server at all.
  2. A **contained database user** created *inside* the database, mapped to the VM's managed identity, with an appropriate role (e.g. `db_datareader` + `db_datawriter`, matching the scenario's read/write demo usage) — this step is SQL DDL (`CREATE USER ... FROM EXTERNAL PROVIDER`), not a Pulumi/ARM resource, so it can't be expressed as an `azure-native` resource the way the storage role assignment can (see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)).
- **The SQL admin login isn't removed, only stopped being the VM's path in.** `administrator_login` / `administrator_login_password` still need to exist on `sql.Server` (Azure SQL Database requires at least one server admin, SQL or Azure AD, at creation), but once an Azure AD administrator is set, the VM/demo path stops depending on the SQL login entirely. Whether to keep exporting `db_admin_password` as a stack output afterward is an open question below — it stops being needed for the demo's normal flow either way.
- **VS Code extensions move from SQL login to Azure AD auth.** The `ms-mssql.mssql` connection profile's `authenticationType` changes from `SqlLogin` to `AzureMFA` (interactive Azure AD sign-in) or, if the extension supports it for this scenario, a managed-identity-aware auth type — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing). Either way, `user`/`password`/`savePassword` are dropped from the profile — there's no password to pre-seed or blank out. `ms-azuretools.vscode-azurestorage`'s "Attach Storage Account..." flow moves from connection-string entry to the extension's Azure AD sign-in ("Sign in to Azure...") against the subscription, since a managed identity isn't something a human interactively assumes from inside VS Code running on their own machine — see open question below on what this means for the demo's operator experience.
- **Control-plane RBAC is scoped to the resource group, not the subscription.** Whoever manages this deployment (the demo operator, and anyone else on the project) gets a role assignment scoped to `rse-cloud-cybersecurity-rg` specifically, not a subscription-wide Owner/Contributor grant — narrowing blast radius to this one resource group even for the humans doing the managing, mirroring the least-privilege approach already applied to the VM's own identity above.
- **Minimum-cost stays intact.** Managed identity and RBAC role assignments carry no additional Azure cost — this iteration changes the access *mechanism*, not the resource SKUs/tiers from `01-the-scenario.md`.
- **Tests stay mock-based, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).** No `pulumi up`/`pulumi preview` as part of building this — new/changed resources (identity block, role assignment, AAD administrator) get unit tests via `pulumi.runtime.set_mocks`, same pattern as the existing suite.

## Changes by resource

### Virtual machine (`infra/compute.py`)

- Add `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` to the `compute.VirtualMachine` resource. This is the only change to the VM resource itself — Azure provisions a service principal in Entra ID tied to the VM's lifecycle, exposed on the resource as `identity.principal_id`.
- `cloud-init` / the pre-created `mssql.connections` profile (`_vscode_settings_json` in `infra/compute.py`) changes as described above — `authenticationType` switches away from `SqlLogin`, and the `user`/`password`/`savePassword` keys are dropped. The profile still needs `server` and `database`, which are unaffected.
- No change to `os_profile` (VM login stays password-based — deferred to the SSH-key iteration).

### Storage account access (new: `infra/access.py` or extend `infra/storage.py`)

- New `authorization.RoleAssignment`:
  - `principal_id=virtual_machine.identity.principal_id`
  - `principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL` — the VM's identity is a service principal, not a user, so this must be set explicitly (Azure AD replication delay makes this matter — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)).
  - `role_definition_id` — the built-in **Storage Blob Data Contributor** role's fully-qualified ID (`/subscriptions/<sub>/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe`), looked up at deploy time via `authorization.get_role_definition_output` or hardcoded (it's a fixed, well-known built-in role GUID — same across all Azure tenants).
  - `scope` — the storage account's `id` (account-wide) or, tighter, the blob container's `id` if container-scoped role assignments are supported for this role (need to confirm — see open questions). Account-wide is the simpler starting point.
- `__main__.py`'s `storage_account_primary_key` export and the `list_storage_account_keys_output` call are removed — no key is generated/read for the demo path once RBAC is in place. (The keys still exist on the account unless key-based auth is separately disabled — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing) on whether to go further and disable `shared_key_access` be disabled entirely.)

### Database access (`infra/database.py`)

- New `sql.ServerAzureADAdministrator` resource, setting an Azure AD principal (a user, group, or service principal — see open question on *which* principal, since this is normally a human/group, not the VM itself) as the server's Azure AD admin. This is what makes Azure AD authentication possible against the server at all; it's a prerequisite, not the VM's own grant.
- The VM's managed identity still needs an explicit **database-level** grant — `CREATE USER [rse-vm] FROM EXTERNAL PROVIDER;` plus `ALTER ROLE db_datareader/db_datawriter ADD MEMBER [rse-vm];` run once against the database, using the VM's display name (matching its Azure resource name, `rse-vm`) as the login name Azure AD resolves it by. This is SQL DDL, not a resource `pulumi_azure_native` can express — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing) for how this fits into the "no live deployment work" constraint.
- `sql.Server`'s `administrator_login`/`administrator_login_password` and the `pulumi_random.RandomPassword` generating it stay in the program (still required at server creation) but stop being part of the VM's runtime access path.

## RBAC for human/operator access

Separate from scoping the VM's *own* access above, this iteration also uses RBAC to tighten who can manage the deployment's resources at the Azure control-plane level — i.e. `Microsoft.Authorization`-governed access to create/modify/delete the resource group's contents, as opposed to the storage/database *data-plane* access covered under [Changes by resource](#changes-by-resource).

- **Resource-group-scoped role assignment(s)** — a new `authorization.RoleAssignment` (or several, one per operator) with `scope=resource_group.id`, granting each person who needs to run `pulumi up`/manage these resources a role scoped to `rse-cloud-cybersecurity-rg` only, rather than relying on a pre-existing subscription-level Owner/Contributor grant outside Pulumi's control.
- **Which built-in role** depends on what the operator actually needs to do:
  - **Contributor**, scoped to the resource group, for whoever runs deployments (create/update/delete any resource in the group, but no access to *grant others access* — that needs `Microsoft.Authorization/roleAssignments/write`, which Contributor deliberately excludes).
  - **Reader**, scoped to the resource group, for anyone who only needs to view the deployment (e.g. to retrieve non-secret stack outputs or inspect resource state) without being able to change anything.
  - Full **Owner** at the resource-group scope is avoidable here — nothing in this scenario needs the ability to manage RBAC itself at that scope; it's called out explicitly as something to avoid defaulting to.
- **This is additive to, not a replacement for, the data-plane RBAC above.** A human with Contributor on the resource group can still see/manage the storage account and SQL server as Azure resources, but that's a separate permission from being able to read blob data or query the database — those still go through the VM's managed identity (or, per the open question on the VS Code extensions, the operator's own Azure AD identity granted the equivalent data-plane roles) rather than through this control-plane grant.
- **Who the role assignment(s) go to** is an open question below — this plan doesn't yet know the concrete list of Azure AD principals (people/groups) that should hold these roles.

## Secrets and config

- **Removed** from the VM's access path once this lands: `db_admin_password` (VM no longer needs it) and the storage account key export (`storage_account_primary_key`). Whether they're removed from `__main__.py`'s exports entirely, or kept only as a break-glass credential a human can still retrieve, is an open question below.
- **No new secrets introduced.** Managed identity tokens are issued and rotated by Azure automatically; nothing new is generated by Pulumi or stored in state.
- **New non-secret config**, if the Azure AD admin principal is supplied via config rather than looked up: something like `sql-aad-admin-object-id` / `sql-aad-admin-login` (non-secret — an Azure AD object ID and display name are not secrets), naming the human/group who administers the server's Azure AD auth.

## Testing plan

Extending the existing `pulumi.runtime.set_mocks`-based suite (mirroring the module layout per [`01-the-scenario.md`](01-the-scenario.md#module-layout)):

- `tests/test_compute.py` — assert the VM resource's `identity.type` is `SystemAssigned`; assert the rendered `custom_data` no longer embeds `SqlLogin`/a `user`/`password` key in the `mssql.connections` profile once the profile format changes.
- New/extended test for the storage role assignment — assert an `authorization.RoleAssignment` exists, scoped to the storage account, with the Storage Blob Data Contributor role definition ID, and `principal_type=ServicePrincipal`.
- `tests/test_database.py` — assert a `sql.ServerAzureADAdministrator` resource exists on the server.
- New/extended test for the resource-group-scoped operator role assignment(s) — assert each `authorization.RoleAssignment` for a human/operator principal has `scope=resource_group.id` (not the subscription) and the expected built-in role definition ID (Contributor or Reader, per principal).
- Per [`01-the-scenario.md`'s testing plan](01-the-scenario.md#testing-plan), the earlier scenario's tests deliberately didn't assert on identity/RBAC presence, since that posture was out of scope then — this iteration is where those tests get added, per that document's own note.
- Still no live Azure calls — `MockResourceArgs`/`MockCallArgs`, run via `uv run pytest`, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature). The database-level `CREATE USER ... FROM EXTERNAL PROVIDER` DDL step (not a Pulumi resource) is outside what mocked unit tests can cover at all — see open questions.

## Migration / rollout notes

- This is not a from-scratch resource — it changes an **existing, potentially-already-deployed** stack. `identity` on an existing VM and a new `RoleAssignment`/`ServerAzureADAdministrator` are additive changes Pulumi can apply in place (no VM replacement expected — unlike the `custom_data` change path noted in `01-the-scenario.md`, this doesn't touch `osProfile.customData`'s *existing* keys in a way that forces `replace_on_changes`, though the `mssql.connections` profile content inside `custom_data` does change, which **does** force a VM replace under the existing `replace_on_changes=["osProfile.customData"]` policy — worth calling out explicitly to whoever runs the deploy).
- Order of operations for a human running this (not Claude, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature)):
  1. `pulumi up` to create the VM identity, role assignment, and AAD administrator.
  2. Manually run the `CREATE USER ... FROM EXTERNAL PROVIDER` / role-membership DDL against the database (as the Azure AD admin) — this can't be part of the Pulumi program itself (see open questions).
  3. Re-attach the storage account in VS Code via Azure AD sign-in, and reconnect the mssql profile, confirming both now work without the old key/password.
  4. Only after confirming the new paths work, consider revoking/rotating the old storage key and SQL admin password (or leave them as a documented break-glass path — open question).

## Out of scope (still deferred)

Per [`01-the-scenario.md`'s planned follow-up](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario), this iteration is identity/RBAC only. Still deferred to later iterations:

- VNet-integrated / private database access (service endpoints or private link) and removing the `0.0.0.0`–`255.255.255.255` SQL firewall rule.
- Narrowing the NSG's SSH/RDP rules to a trusted IP range instead of `Internet`/`0.0.0.0/0`.
- SSH key authentication on the VM instead of password auth (VM login is unrelated to the resource-access identity work here).
- Azure Bastion or another jump-host pattern instead of a directly internet-facing VM.

## Open questions / assumptions to confirm before implementing

1. **Who is the Azure AD administrator on the SQL server?** `sql.ServerAzureADAdministrator` needs a real Azure AD principal (a person's account, or a group) — not the VM's own identity, which only needs a *database user*, not server-admin rights. Needs a name/object ID from whoever owns the Azure AD tenant for this project.
2. **Can the container-level RBAC scope be used instead of account-level?** Confirm whether Storage Blob Data Contributor can be assigned at the `BlobContainer` scope (tighter) rather than the whole `StorageAccount` (simpler) — affects the `scope=` argument on `RoleAssignment`.
3. **Should storage account key access be disabled outright** (`storage.StorageAccount.allow_shared_key_access=False`) once RBAC is confirmed working, or left enabled as a break-glass fallback? Disabling it is the stronger security posture but forecloses the key-based path entirely, including for any tooling that doesn't support Azure AD auth.
4. **How does `ms-mssql.mssql` actually express Azure AD / managed-identity auth from inside a VS Code session running as the VM's own identity**, versus a human interactively signing in? The extension's `AzureMFA` auth type is built for a human's interactive Azure AD sign-in, not a system-assigned managed identity a background process would use silently — worth confirming what "VS Code as the only interface" concretely looks like post-change, since it may mean the operator now authenticates as *themselves* (via their own Azure AD account, granted the same RBAC roles) rather than genuinely riding the VM's managed identity token from inside the editor. If so, the VM's managed identity secures things like any headless/background access path, while the interactive VS Code demo may need the operator's own Azure AD identity granted the same roles — worth deciding explicitly rather than assuming.
5. **Where does the `CREATE USER ... FROM EXTERNAL PROVIDER` DDL step live?** It can't be a Pulumi resource. Options: a one-off script the human runs manually as part of rollout (documented in this file), or a `local-command`/`command.local.Command`-style Pulumi resource that shells out to `sqlcmd`/`ms-mssql` — the latter would reintroduce a CLI dependency the scenario deliberately avoided on the VM, though it could run from the operator's own machine rather than the VM. Leaning toward a documented manual step for now, consistent with keeping this out of automated deploys per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).
6. **Do the old SQL admin password and storage key stay as exported secret stack outputs after this lands**, for break-glass access, or are they dropped from `__main__.py`'s exports (while the underlying credentials still exist on the resources, just no longer surfaced)? Leaning toward dropping the exports, since the RDP/SSH admin password stack output remains available as the operator's actual entry point if something's wrong.
7. **Who are the concrete Azure AD principals for the resource-group-scoped operator role assignments?** Needs the actual list of people/groups managing this deployment (likely just the current operator, to start) and which of them need Contributor versus Reader — probably supplied via new non-secret config (e.g. `operator-object-ids`) rather than hardcoded, mirroring how `db-admin-username`/`vm-admin-username` are already configured.
8. **Is a pre-existing subscription-level Owner/Contributor grant already in place for the current operator**, outside of Pulumi's management? If so, adding a narrower resource-group-scoped role here doesn't remove the broader one — actually shrinking blast radius would also require revoking or downgrading that subscription-level grant, which is an Azure AD/subscription-administration action outside this Pulumi program's reach (and outside what Claude should do live, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature)) — worth flagging to whoever administers the subscription rather than assuming this plan alone closes that gap.
