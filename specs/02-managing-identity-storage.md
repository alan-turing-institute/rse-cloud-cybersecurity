# 02 — Managing Identity: Storage Account Access

A plan for part of the first security-hardening iteration flagged as out of scope in [`01-the-scenario.md`](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario): replacing the VM's storage access path (the storage account key) with **Azure Managed Identity** and RBAC, so the VM reads from the storage account without depending on any long-lived secret being generated, exported, or typed in by hand. The storage account key keeps existing and keeps being exported — it just stops being the VM's own path in, and remains purely as a management/break-glass credential for a human — see [Secrets and config](#secrets-and-config).

This is the **storage half** of the managing-identity iteration. The companion plan, [`03-managing-identity-database.md`](03-managing-identity-database.md), covers the database access path; the two are independent and can be implemented (and deployed) in either order. Both rely on the same VM system-assigned identity — see the note under [Design principles](#design-principles).

This plan covers **identity only**, scoped to the VM's own access to storage. RBAC for human/operator access to the resource group, VNet segmentation, Azure Bastion, NSG narrowing, and SSH-key auth all remain deferred to their own later iterations — see [Out of scope](#out-of-scope-still-deferred) below.

## Why this matters

The current deployment (see [`01-the-scenario.md`](01-the-scenario.md)) has the VM using the storage account's primary access key — a static, all-or-nothing credential with full control over every container/blob in the account, exported via `pulumi.Output.secret(storage_account_keys.keys[0].value)` in `__main__.py` and pasted into VS Code by hand after `pulumi stack output --show-secrets`.

This is a long-lived, broad-access credential (account-level key) that exists as a plaintext-capable secret outside Azure's own identity system — in Pulumi state (encrypted, but still a shared secret) and briefly in a human's clipboard. Managed identity removes the VM's *dependency* on that secret: Azure issues short-lived tokens to the VM's identity, and an RBAC role assignment scopes exactly what that identity can do. The key itself isn't removed from the deployment — it stays available for a human to use directly for management, per [Secrets and config](#secrets-and-config).

## Goal

- The VM authenticates to the storage account using its **system-assigned managed identity** — no API key.
- Storage access is **read-only, and scoped to the `rse-demo-container` blob container only** — every other container on the account (present or future) is out of bounds for the VM's identity.
- No new secrets are introduced for the VM's own storage access path.

## Design principles

- **System-assigned, not user-assigned, managed identity.** The VM is the only resource that needs this identity, its lifecycle should match the VM's exactly (created/destroyed with it), and there's no need to share the identity across multiple resources. A system-assigned identity is the simplest fit; user-assigned would only pay off if a second resource needed the same identity. **This identity is shared infrastructure with [`03-managing-identity-database.md`](03-managing-identity-database.md)** — both plans call for the same `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` on the VM resource. Whichever of the two plans is implemented first adds it; if the other has already landed, this step is already done and is a no-op to re-specify.
- **RBAC role assignment scoped to the one container, read-only.** `storage.StorageAccount` and `blob_container` keep existing — only the *access path* changes. The VM's managed identity gets an `authorization.RoleAssignment` scoped to the `rse-demo-container` blob container specifically (not the whole storage account) with the **Storage Blob Data Reader** role — read-only on that container's blob data, no write, no account management, no key access, and no reach into any other container that might later exist on the same account.
- **The storage account key isn't removed — it stops being the VM's path in, and is kept for management.** The storage account's keys still exist by default. Once the managed-identity path is in place, the VM stops depending on it, but the key stays exported as a secret stack output so a human can still manage/troubleshoot the account directly (e.g. using `az` outside the VM) — see [Secrets and config](#secrets-and-config).
- `ms-azuretools.vscode-azurestorage`'s "Attach Storage Account..." flow moves from connection-string entry to the extension's Azure AD sign-in ("Sign in to Azure...") against the subscription, since a managed identity isn't something a human interactively assumes from inside VS Code running on their own machine — see open question below on what this means for the demo's operator experience.
- **Minimum-cost stays intact.** Managed identity and the RBAC role assignment carry no additional Azure cost — this iteration changes the access *mechanism*, not the resource SKUs/tiers from `01-the-scenario.md`.
- **Tests stay mock-based, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).** No `pulumi up`/`pulumi preview` as part of building this — the identity block and role assignment get unit tests via `pulumi.runtime.set_mocks`, same pattern as the existing suite.

## Changes by resource

### Virtual machine (`infra/compute.py`)

- Add `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` to the `compute.VirtualMachine` resource (see the shared-identity note under [Design principles](#design-principles)). This is the only change this plan makes to the VM resource itself — Azure provisions a service principal in Entra ID tied to the VM's lifecycle, exposed on the resource as `identity.principal_id`.
- No change to `os_profile` (VM login stays password-based — deferred to the SSH-key iteration) and no change to the `mssql.connections` cloud-init profile — that's [`03-managing-identity-database.md`](03-managing-identity-database.md)'s concern.

### Storage account access (`infra/storage.py`)

The RBAC role assignment for storage lives alongside the resources it grants access to, in `infra/storage.py` — no separate `access.py`/access-control module.

- New `authorization.RoleAssignment` in `infra/storage.py`:
  - `principal_id=virtual_machine.identity.principal_id`
  - `principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL` — the VM's identity is a service principal, not a user, so this must be set explicitly (Azure AD replication delay makes this matter — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)).
  - `role_definition_id` — the built-in **Storage Blob Data Reader** role's fully-qualified ID (`/subscriptions/<sub>/providers/Microsoft.Authorization/roleDefinitions/2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`), looked up at deploy time via `authorization.get_role_definition_output` or hardcoded (it's a fixed, well-known built-in role GUID — same across all Azure tenants). Read-only, matching the goal above — not Storage Blob Data Contributor.
  - `scope=blob_container.id` — the `rse-demo-container` container specifically, not the storage account. This is what keeps any other container on the account out of the VM's reach, per the goal above (needs confirming that container-scoped assignment is supported for this role — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)).
- `__main__.py`'s `storage_account_primary_key` export and the `list_storage_account_keys_output` call **stay as they are** — the VM stops using the key, but the key itself, and its stack output, are kept for management purposes (a human managing the account directly). See [Secrets and config](#secrets-and-config).

## Verifying storage access from VS Code (manual)

The primary, day-to-day way to confirm the managed identity + RBAC grant work is the same GUI flow the operator uses for the demo itself — `ms-azuretools.vscode-azurestorage`'s "Attach Storage Account..." flow (see [Design principles](#design-principles)), run from an RDP/SSH session on the VM:

1. **Sign in to Azure** — in VS Code's Azure Storage extension, choose "Attach Storage Account..." → "Sign in to Azure...", and complete the interactive Azure AD sign-in (device code or browser) against the subscription.
2. **Browse to `rse-demo-container`** and confirm its blob listing loads in the extension's tree view (empty is fine if the container has nothing in it yet) — this exercises the Storage Blob Data Reader role assignment.
3. **Confirm the scope is as narrow as intended** — browsing to a different container on the same account (or another storage account) should fail to list its contents, with an access-denied error surfaced by the extension.
4. **Confirm read-only** — attempting to upload a file or delete a blob inside `rse-demo-container` through the extension's UI should fail with an access-denied error, confirming Storage Blob Data *Reader* (not *Contributor*) behavior.
5. **Caveat:** VS Code's "Sign in to Azure..." flow is interactive human sign-in, not the VM's managed identity (see [Design principles](#design-principles)) — so this check directly verifies the RBAC role/scope combination is configured correctly for whichever Azure AD account is signed in, not that the *VM's own* managed identity specifically has been granted it. For a check that genuinely exercises the VM's system-assigned identity end to end, use [Verifying storage access via IMDS and curl](#verifying-storage-access-via-imds-and-curl-manual-low-level) below.

This is a manual, human-run check (consistent with [`CLAUDE.md`'s no-live-deployment rule](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) — Claude doesn't run this against live Azure resources); it's referenced from [Migration / rollout notes](#migration--rollout-notes) as a sanity check before treating the demo as ready.

## Verifying storage access via IMDS and curl (manual, low-level)

As a lower-level alternative to the VS Code check above — and the only one of the two that genuinely exercises the *VM's own* managed identity rather than a human's Azure AD sign-in — the identity and RBAC grant can also be checked directly from an RDP/SSH session on the VM, using nothing but `curl` (already present on any Ubuntu image — no new tooling). This follows Microsoft's own tutorial pattern for exercising a Linux VM's managed identity against Azure Storage ([Tutorial: Use a Linux VM/VMSS to access Azure resources](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/tutorial-linux-managed-identities-vm-access)):

1. **Get a token from the VM's local managed identity endpoint (IMDS)**, scoped to the storage resource:
   ```bash
   curl 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' -H Metadata:true
   ```
   A successful response is a JSON blob with an `access_token` field — this alone confirms the VM's system-assigned managed identity is attached and Azure will issue it tokens. Capture the token into a variable for the next steps:
   ```bash
   access_token=$(curl 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' -H Metadata:true | jq -r '.access_token')
   ```
   (`jq` may need installing — `sudo apt-get install -y jq` — or the token can be copied out of the raw JSON by hand.)
2. **Confirm read access to `rse-demo-container` works** — list the container's contents via the Blob REST API:
   ```bash
   curl -i "https://<STORAGE ACCOUNT>.blob.core.windows.net/rse-demo-container?restype=container&comp=list" \
     -H "x-ms-version: 2021-08-06" \
     -H "Authorization: Bearer $access_token"
   ```
   Expect **`200 OK`** with an XML blob listing (empty is fine if the container has nothing in it yet) — this confirms the Storage Blob Data Reader role assignment is actually in effect for the VM's identity.
3. **Confirm the scope is as narrow as intended** — the same request against a different container (or the account root, or a second storage account) should come back **`403 Forbidden`**, proving the role assignment is genuinely scoped to `rse-demo-container` and not the whole account.
4. **Confirm read-only** — attempt a write (e.g. `PUT` a blob into `rse-demo-container`) with the same token; expect **`403 Forbidden`**, confirming Storage Blob Data *Reader* (not *Contributor*) is what's actually granted.
5. If any of steps 2–4 doesn't return the expected status, the likely causes are: the `RoleAssignment` hasn't propagated yet (Azure AD role assignment propagation can take a few minutes — retry after waiting), the `scope` ended up account-wide rather than container-scoped (see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)), or the wrong role definition ID was used.

This is a manual, human-run check (consistent with [`CLAUDE.md`'s no-live-deployment rule](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) — Claude doesn't run this against live Azure resources); it's referenced from [Migration / rollout notes](#migration--rollout-notes) as an optional sanity check before moving on to VS Code.

## Secrets and config

- **The storage account key (`storage_account_primary_key`) keeps being exported as a secret stack output**, unchanged from today — it's no longer part of the VM's own access path, but is kept specifically for **management purposes**: an operator managing the storage account directly (e.g. via `az`) outside of what the VM's managed identity is scoped to do.
- **No new secrets introduced** for the VM's own storage access. Managed identity tokens are issued and rotated by Azure automatically; nothing new is generated by Pulumi or stored in state for that path.

## Testing plan

Extending the existing `pulumi.runtime.set_mocks`-based suite (mirroring the module layout per [`01-the-scenario.md`](01-the-scenario.md#module-layout)):

- `tests/test_compute.py` — assert the VM resource's `identity.type` is `SystemAssigned`.
- `tests/test_storage.py` — assert an `authorization.RoleAssignment` exists, scoped to `blob_container.id` (not the storage account), with the Storage Blob Data **Reader** role definition ID, and `principal_type=ServicePrincipal`; assert `storage_account_primary_key`/the underlying key export is still present (i.e. no regression removing the management-purpose export).
- Per [`01-the-scenario.md`'s testing plan](01-the-scenario.md#testing-plan), the earlier scenario's tests deliberately didn't assert on identity/RBAC presence, since that posture was out of scope then — this iteration is where those tests get added, per that document's own note.
- Still no live Azure calls — `MockResourceArgs`/`MockCallArgs`, run via `uv run pytest`, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).

## Migration / rollout notes

- This is not a from-scratch resource — it changes an **existing, potentially-already-deployed** stack. `identity` on an existing VM and a new `RoleAssignment` are additive changes Pulumi can apply in place (no VM replacement expected).
- Order of operations for a human running this (not Claude, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature)):
  1. `pulumi up` to create the VM identity and role assignment.
  2. Optionally, from an RDP/SSH session on the VM, run through [Verifying storage access from VS Code](#verifying-storage-access-from-vs-code-manual) — or, to check the VM's own managed identity directly, [Verifying storage access via IMDS and curl](#verifying-storage-access-via-imds-and-curl-manual-low-level) — to confirm the managed identity + RBAC grant work as expected before treating the demo as ready.
  3. Re-attach the storage account in VS Code via Azure AD sign-in.
  4. The storage account key stays exported and in place throughout — it's kept deliberately, for management, not something to revoke or rotate as part of this rollout.

## Out of scope (still deferred)

Per [`01-the-scenario.md`'s planned follow-up](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario), this iteration is identity/RBAC only. Still deferred to later iterations:

- VNet-integrated / private database access (service endpoints or private link) and removing the `0.0.0.0`–`255.255.255.255` SQL firewall rule — see [`03-managing-identity-database.md`](03-managing-identity-database.md).
- Narrowing the NSG's SSH/RDP rules to a trusted IP range instead of `Internet`/`0.0.0.0/0`.
- SSH key authentication on the VM instead of password auth (VM login is unrelated to the resource-access identity work here).
- Azure Bastion or another jump-host pattern instead of a directly internet-facing VM.
- **RBAC for human/operator access to the resource group** (e.g. moving off a subscription-level Owner/Contributor grant to a resource-group-scoped role). This iteration only scopes the VM's own access; who can manage the deployment's Azure resources is not addressed here.

## Open questions / assumptions to confirm before implementing

1. **Does container-scoped `RoleAssignment` actually work for Storage Blob Data Reader as expected** (`scope=blob_container.id`)? Worth a final check against current Azure RBAC docs at implementation time — container-scoped assignments are supported for this role, but it's the kind of detail worth confirming rather than assuming, per this repo's existing convention (cf. `01-the-scenario.md`'s open questions on Public IP SKU retirement). [Verifying storage access via IMDS and curl](#verifying-storage-access-via-imds-and-curl-manual-low-level) above is exactly how to confirm this once deployed, since it exercises the VM's own identity precisely and returns unambiguous HTTP status codes.
