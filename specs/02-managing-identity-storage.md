# 02 — Managing Identity: Storage Account Access

A plan for part of the first security-hardening iteration flagged as out of scope in [`01-the-scenario.md`](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario): replacing the VM's storage access path (the storage account key) with **Azure Managed Identity** and RBAC, so the VM reads from the storage account without depending on any long-lived secret being generated, exported, or typed in by hand. The storage account key keeps existing and keeps being exported — it just stops being the VM's own path in, and remains purely as a management/break-glass credential for a human — see [Secrets and config](#secrets-and-config).

The VM's own access is via a **filesystem mount**, not the Blob REST API called by hand: `rse-demo-container` is mounted directly on the VM's Linux filesystem, using [BlobFuse2](https://github.com/Azure/azure-storage-fuse) authenticating with the managed identity. Once mounted, the container behaves like an ordinary local directory to any tool on the VM — VS Code's file explorer, a terminal, `cat`/`ls` — with no Azure-aware sign-in step required at all. See [Design principles](#design-principles) for why this replaces the earlier direct-REST-API approach.

This is the **storage half** of the managing-identity iteration. The companion plan, [`03-managing-identity-database.md`](03-managing-identity-database.md), covers the database access path; the two are independent and can be implemented (and deployed) in either order. Both rely on the same VM system-assigned identity — see the note under [Design principles](#design-principles).

This plan covers **identity only**, scoped to the VM's own access to storage. RBAC for human/operator access to the resource group, VNet segmentation, Azure Bastion, NSG narrowing, and SSH-key auth all remain deferred to their own later iterations — see [Out of scope](#out-of-scope-still-deferred) below.

## Why this matters

The current deployment (see [`01-the-scenario.md`](01-the-scenario.md)) has the VM using the storage account's primary access key — a static, all-or-nothing credential with full control over every container/blob in the account, exported via `pulumi.Output.secret(storage_account_keys.keys[0].value)` in `__main__.py` and pasted into VS Code by hand after `pulumi stack output --show-secrets`.

This is a long-lived, broad-access credential (account-level key) that exists as a plaintext-capable secret outside Azure's own identity system — in Pulumi state (encrypted, but still a shared secret) and briefly in a human's clipboard. Managed identity removes the VM's *dependency* on that secret: Azure issues short-lived tokens to the VM's identity, and an RBAC role assignment scopes exactly what that identity can do. The key itself isn't removed from the deployment — it stays available for a human to use directly for management, per [Secrets and config](#secrets-and-config).

## Goal

- The VM authenticates to the storage account using its **system-assigned managed identity** — no API key.
- The `rse-demo-container` blob container is **mounted as a directory on the VM's own filesystem**, so the operator (and any tool they use — VS Code, a terminal, a file manager) reads it like ordinary local files, with no separate Azure sign-in step and no manual REST calls.
- Storage access is **read-only, and scoped to the `rse-demo-container` blob container only** — every other container on the account (present or future) is out of bounds for the VM's identity, both at the mount layer and at the RBAC layer underneath it.
- No new secrets are introduced for the VM's own storage access path.

## Design principles

- **System-assigned, not user-assigned, managed identity.** The VM is the only resource that needs this identity, its lifecycle should match the VM's exactly (created/destroyed with it), and there's no need to share the identity across multiple resources. A system-assigned identity is the simplest fit; user-assigned would only pay off if a second resource needed the same identity. **This identity is shared infrastructure with [`03-managing-identity-database.md`](03-managing-identity-database.md)** — both plans call for the same `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` on the VM resource. Whichever of the two plans is implemented first adds it; if the other has already landed, this step is already done and is a no-op to re-specify.
- **RBAC role assignment scoped to the one container, read-only.** `storage.StorageAccount` and `blob_container` keep existing — only the *access path* changes. The VM's managed identity gets an `authorization.RoleAssignment` scoped to the `rse-demo-container` blob container specifically (not the whole storage account) with the **Storage Blob Data Reader** role — read-only on that container's blob data, no write, no account management, no key access, and no reach into any other container that might later exist on the same account. This is the same role/scope regardless of whether the VM talks to the REST API directly or through a mount — BlobFuse2 is just another client making the same authenticated calls. (This role assignment is defined in `infra/compute.py`, not `infra/storage.py` — see the note under [Changes by resource](#changes-by-resource).)
- **Mount with BlobFuse2, authenticating via managed identity — this is why no GUI tool's own Azure sign-in is needed.** Earlier drafts of this plan tried to verify the managed-identity path through VS Code's `ms-azuretools.vscode-azurestorage` extension and Azure Storage Explorer, and found neither actually authenticates as a VM's managed identity — both only offer interactive human Microsoft Entra ID sign-in, an account key, or a SAS ([Get started with Storage Explorer](https://learn.microsoft.com/en-us/azure/storage/storage-explorer/vs-azure-tools-storage-manage-with-storage-explorer)). Mounting the container with [BlobFuse2](https://github.com/Azure/azure-storage-fuse) — Microsoft's own FUSE driver for Blob Storage — sidesteps that problem entirely: BlobFuse2 itself talks to Azure AD and the VM's local IMDS endpoint (`mode: msi` in its config), so *it* does the token dance that `curl` did by hand in earlier drafts, and every other tool on the VM (VS Code, `ls`, a file manager) just sees a normal directory. Nothing above BlobFuse2 needs to know Azure AD exists.
  - `ms-azuretools.vscode-azurestorage`'s "Attach Storage Account..." flow and Azure Storage Explorer remain installed/available, unchanged, for a human doing account-level **management** (browsing other containers, checking blob metadata) using the retained account key or their own Azure AD sign-in — see [Secrets and config](#secrets-and-config). They are simply no longer part of *the VM's own* access path, which the mount now handles.
- **`packages.microsoft.com`'s apt repo is shared infrastructure with [`03-managing-identity-database.md`](03-managing-identity-database.md).** Both BlobFuse2 (this plan) and `sqlcmd`/go-sqlcmd (the database plan) install from the same Microsoft-hosted apt repo, configured via the `packages-microsoft-prod.deb` bootstrap package. Whichever plan is implemented first adds the repo; `dpkg -i` on an already-installed identical package is a safe no-op, so the second plan re-specifying the same step doesn't conflict.
- **The storage account key isn't removed — it stops being the VM's path in, and is kept for management.** The storage account's keys still exist by default. Once the managed-identity path is in place, the VM stops depending on it, but the key stays exported as a secret stack output so a human can still manage/troubleshoot the account directly (e.g. using `az`, or the VS Code/Storage Explorer tools above, outside the VM) — see [Secrets and config](#secrets-and-config).
- **Minimum-cost stays intact.** Managed identity, the RBAC role assignment, and BlobFuse2 (free, open-source software installed via `apt`) carry no additional Azure cost — this iteration changes the access *mechanism*, not the resource SKUs/tiers from `01-the-scenario.md`.
- **Tests stay mock-based, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature).** No `pulumi up`/`pulumi preview` as part of building this — the identity block and role assignment get unit tests via `pulumi.runtime.set_mocks`, and the rendered cloud-init content (BlobFuse2 config, systemd unit) gets asserted against directly, same pattern as the existing suite. No live mount is attempted.

## Changes by resource

### Virtual machine (`infra/compute.py`)

- Add `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` to the `compute.VirtualMachine` resource (see the shared-identity note under [Design principles](#design-principles)). This is the only change this plan makes to the VM resource itself — Azure provisions a service principal in Entra ID tied to the VM's lifecycle, exposed on the resource as `identity.principal_id`.
- `infra/compute.py` gains a new import, `blob_container, storage_account` from `infra.storage` (mirroring the existing `from infra.database import sql_database, sql_server`), since `_custom_data` now also needs the storage account name to render the BlobFuse2 config. `custom_data`'s `pulumi.Output.all(...)` call grows a third argument, `storage_account.name`.
- **New cloud-init steps**, added to `infra/templates/vm-cloud-init.yaml.j2` alongside the existing VS Code/Chrome install steps (see [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2) below for the full detail):
  1. Install `fuse3` and `blobfuse2` from the `packages.microsoft.com` apt repo (shared step — see [Design principles](#design-principles)).
  2. Uncomment `user_allow_other` in `/etc/fuse.conf`, so a non-root operator session can read files from a mount owned by the cloud-init/systemd process.
  3. Create the mount point (`/mnt/rse-demo-container`), the BlobFuse2 config directory (`/etc/blobfuse2`), and its local cache directory (`/var/cache/blobfuse2/rse-demo-container`).
  4. Write the rendered BlobFuse2 config file and a systemd unit (both base64-embedded and decoded via `runcmd`, the same pattern already used for `vscode_settings_b64`).
  5. `systemctl daemon-reload` and `systemctl enable --now` the new unit, so the mount comes up automatically on every boot, not just the first one.
- No change to `os_profile` (VM login stays password-based — deferred to the SSH-key iteration) and no change to the `mssql.connections` cloud-init profile — that's [`03-managing-identity-database.md`](03-managing-identity-database.md)'s concern.
- **Resolved during implementation: the RBAC role assignment lives in `infra/compute.py`, not `infra/storage.py`.** The original design principle below ("lives alongside the resources it grants access to") assumed `infra/storage.py` wouldn't need anything from `infra/compute.py`. That held before this plan, but no longer does: `infra/compute.py` now imports `storage_account` (and `blob_container`) from `infra/storage.py` for the BlobFuse2 config, so having `infra/storage.py` import `virtual_machine` back from `infra/compute.py` for the role assignment's `principal_id` would be a genuine Python circular import, not just a style question. The role assignment is therefore defined in `infra/compute.py`, right after the `compute.VirtualMachine` resource — the one module that already depends on both.

### Storage account access (`infra/storage.py`)

Unchanged — `storage.StorageAccount` and `blob_container` stay exactly as they are. **The RBAC role assignment described in the original design (see the note above) is defined in `infra/compute.py` instead**, but it's otherwise exactly as planned:

- New `authorization.RoleAssignment`, in `infra/compute.py`, right after `virtual_machine`:
  - `principal_id=virtual_machine.identity.principal_id`
  - `principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL` — the VM's identity is a service principal, not a user, so this must be set explicitly (Azure AD replication delay makes this matter — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)).
  - `role_definition_id` — the built-in **Storage Blob Data Reader** role's fully-qualified ID, built from `authorization.get_client_config_output().subscription_id` plus the fixed, well-known built-in role GUID `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` (same across all Azure tenants) via `pulumi.Output.concat(...)`. Read-only, matching the goal above — not Storage Blob Data Contributor. This is sufficient for BlobFuse2's read/list operations; no elevated role is needed to mount read-only.
  - `scope=blob_container.id` — the `rse-demo-container` container specifically, not the storage account. This is what keeps any other container on the account out of the VM's reach, per the goal above (needs confirming that container-scoped assignment is supported for this role — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)).
- `__main__.py`'s `storage_account_primary_key` export and the `list_storage_account_keys_output` call **stay as they are** — the VM stops using the key, but the key itself, and its stack output, are kept for management purposes (a human managing the account directly). See [Secrets and config](#secrets-and-config).

### Mounting the container with BlobFuse2

Per [`CLAUDE.md`'s preference for Jinja templates over hand-assembled YAML](../CLAUDE.md#prefer-jinja-templates-over-assembling-yaml-in-code), the BlobFuse2 config is its own template, rendered the same way the cloud-init document itself already is.

- New template, `infra/templates/blobfuse2-config.yaml.j2`, rendered with the storage account's name (the only dynamic value it needs — everything else is fixed):
  ```yaml
  allow-other: true
  disable-kernel-cache: true

  components:
    - libfuse
    - file_cache
    - attr_cache
    - azstorage

  file_cache:
    path: /var/cache/blobfuse2/rse-demo-container
    timeout-sec: 120

  attr_cache:
    timeout-sec: 0

  azstorage:
    type: block
    account-name: {{ storage_account_name }}
    container: rse-demo-container
    endpoint: https://{{ storage_account_name }}.blob.core.windows.net
    mode: msi
  ```
  - `mode: msi` with no `appid`/`objid`/`resid` is deliberate: those three fields exist only to disambiguate *which* identity to use when a VM has more than one (a user-assigned identity alongside the system-assigned one); with a single system-assigned identity, BlobFuse2 resolves it automatically via IMDS, and setting none of them is the documented way to say "the one identity this VM has."
  - `account-key`/`sas`/any credential field is absent — there is nothing secret in this file, consistent with the "no new secrets" goal.
  - `type: block` (not `adls`) matches `storage.StorageAccount`'s current configuration in `infra/storage.py` (`kind=storage.Kind.STORAGE_V2` with no hierarchical namespace) — see [Create a BlobFuse configuration file](https://learn.microsoft.com/en-us/azure/storage/blobs/blobfuse2-configure)'s warning that mismatching `type` against the account's actual namespace mode causes mount/directory-operation failures.
  - `allow-other: true` at the file's root (not inside `libfuse:` — the two are separate top-level sections in BlobFuse2's config schema) plus the `/etc/fuse.conf` change above are both needed for a non-root VS Code/RDP session to read the mount; neither alone is sufficient.
  - Read-only is enforced at the **mount command**, not in this file — BlobFuse2 has no `read-only` config-file key; it's a `mount` CLI parameter (`--read-only=true`) — see the systemd unit below.
  - **`disable-kernel-cache: true` and `attr_cache.timeout-sec: 0` — resolved during implementation, after observing the mount come up (`active (running)`) but list `rse-demo-container` as empty.** The retained storage account key deliberately stays usable for a human to manage the container directly (e.g. via the Portal, Storage Explorer, or `az`) — that's the whole point of [keeping it exported](#secrets-and-config). But that means blobs can be added or changed **outside BlobFuse2 entirely**, and Microsoft's own config-file guidance is explicit that this exact situation ("blobs can be modified outside Blobfuse2") requires `disable-kernel-cache: true` plus tuning `attr_cache.timeout-sec` for freshness, rather than relying on the defaults — without it, the kernel's own dentry/attribute cache (and BlobFuse2's `attr_cache`, which otherwise defaults this plan hadn't overridden) can keep showing a stale — e.g. empty — listing after an external change, with no error anywhere to indicate why. `attr_cache.timeout-sec: 0` trades a small amount of extra Blob-listing traffic for always-fresh directory listings; given [Minimum-cost stays intact](#design-principles) and how small/low-traffic this demo container is, that trade is a non-issue here.
- New systemd unit, templated as `infra/templates/blobfuse2.service.j2` (rendered with `mount_path`/`config_path`, then base64-embedded and decoded via `runcmd` alongside the config file — moved out of a Python string literal and into its own templated file for readability, the same reasoning as [`CLAUDE.md`'s Jinja-over-hand-assembled-YAML guideline](../CLAUDE.md#prefer-jinja-templates-over-assembling-yaml-in-code)):
  ```ini
  [Unit]
  Description=Mount rse-demo-container via BlobFuse2 (managed identity)
  After=network-online.target
  Requires=network-online.target

  [Service]
  Type=simple
  ExecStart=/usr/bin/blobfuse2 mount /mnt/rse-demo-container --config-file=/etc/blobfuse2/rse-demo-container.yaml --read-only=true --foreground=true
  ExecStop=/usr/bin/blobfuse2 unmount /mnt/rse-demo-container
  Restart=on-failure
  RestartSec=15

  [Install]
  WantedBy=multi-user.target
  ```
  - **`--foreground=true` is required, not optional, given `Type=simple` — resolved during implementation after observing the failure mode first-hand.** `blobfuse2 mount` daemonizes by default: once the mount is established it forks into the background and the invoking process exits. Under `Type=simple`, systemd tracks *that* invoking process as "the service" — so without `--foreground=true`, the process it's watching exits (cleanly, exit code 0) almost immediately after starting, and `systemctl status` reports the unit as **`inactive`**, not `failed` and not `active (running)`, regardless of whether the underlying mount came up. `--foreground=true` keeps blobfuse2 itself as the long-running process, so the one systemd tracks is the one actually holding the mount open. See [Troubleshooting the mount with IMDS and curl](#troubleshooting-the-mount-with-imds-and-curl-manual) for how this actually surfaced.
  - `Restart=on-failure`/`RestartSec=15` specifically absorbs the known Azure AD role-assignment propagation delay (a few minutes — see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)): if the VM's very first boot runs the mount before the `RoleAssignment` has propagated, systemd retries every 15 seconds rather than leaving the mount permanently failed.
  - `ExecStop` uses `blobfuse2 unmount`, BlobFuse2's own unmount subcommand, rather than a raw `fusermount3 -u`, since it's the tool's documented, more robust way to clean up (it also clears the local file cache directory).
- The mount point, `/mnt/rse-demo-container`, is what the operator (and VS Code, opened against that path) actually browses — no "Attach Storage Account..." step, no sign-in, no stack-output secret to paste in. See [Verifying the mount](#verifying-the-mount-manual) below for confirming this end to end.

## Verifying the mount (manual)

With the mount coming up automatically at boot via the systemd unit above, confirming it works is mostly a matter of looking at the mounted directory like any other filesystem path, from an RDP/SSH session on the VM:

1. **Confirm the service is active:**
   ```bash
   systemctl status blobfuse2-rse-demo-container.service
   ```
   Expect `active (running)`. Two different non-running states point at two different problems:
   - **`inactive`** (a clean exit, not a crash) almost always means the `ExecStart` process daemonized and exited on its own — see the `--foreground=true` note under [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2). `journalctl -u blobfuse2-rse-demo-container.service` showing a line like `Libfuse::libfuse_init : Loaded libfuse runtime does not forward cache_readdir through the high-level API (requires libfuse 3.16.1+), disabling kernel-list-cache` right before the unit went inactive is a **red herring**, not the cause: it's a benign compatibility warning (Ubuntu 22.04's `fuse3` apt package ships a libfuse older than 3.16.1, so BlobFuse2 disables one caching optimization and carries on) that happens to be the last thing logged before the daemonizing process exits.
   - **`failed`**, or repeatedly restarting, points at an actual mount error — see [Troubleshooting the mount with IMDS and curl](#troubleshooting-the-mount-with-imds-and-curl-manual) below.
2. **Confirm read access to `rse-demo-container` works:**
   ```bash
   ls -la /mnt/rse-demo-container
   ```
   This should list the container's contents with no error — proving the Storage Blob Data Reader role assignment is in effect and BlobFuse2 successfully exchanged the VM's managed identity for a usable token. The same directory opens the same way in VS Code (`File > Open Folder...` → `/mnt/rse-demo-container`) or any other GUI file browser on the VM — no Azure-aware tool or sign-in required, per [Design principles](#design-principles).
   - **An empty listing here is only "fine" if the container genuinely has nothing in it.** If blobs were added via the retained account key/Portal/Storage Explorer (see [Secrets and config](#secrets-and-config)) and still don't show up here, don't assume the mount is broken — first confirm what the container actually holds by calling the Blob REST API directly, bypassing BlobFuse2 entirely, via step 2 of [Troubleshooting the mount with IMDS and curl](#troubleshooting-the-mount-with-imds-and-curl-manual). If that `curl` shows blobs the mount doesn't, it's the caching issue described under [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2) (`disable-kernel-cache`/`attr_cache.timeout-sec`) — re-run `ls` after confirming that config actually deployed, rather than assuming the RBAC/identity layer is at fault.
3. **Confirm read-only:**
   ```bash
   touch /mnt/rse-demo-container/test-file.txt
   ```
   Expect `Permission denied` — enforced twice over: by the mount's own `--read-only=true`, and, independently, by the Storage Blob Data *Reader* (not *Contributor*) role underneath it.
4. **Confirm the scope is as narrow as intended** — nothing in the mount config names any container other than `rse-demo-container`, so there's no sibling directory to browse into by construction. To actually exercise the RBAC boundary (rather than just BlobFuse2's own config), temporarily point a *second* config file's `container:` at a different container on the same account and try to mount or list it with the same identity:
   ```bash
   sudo blobfuse2 mount /mnt/scratch-test --config-file=<config with a different container name>
   ```
   Expect this to fail with an authorization error at mount/first-access time, proving the role assignment — not just the config file naming one container — is what actually keeps other containers out of reach. Unmount and remove `/mnt/scratch-test` afterwards.
5. If the service won't start or steps 2–4 don't return the expected result, see [Troubleshooting the mount with IMDS and curl](#troubleshooting-the-mount-with-imds-and-curl-manual) below to isolate whether the problem is the identity/RBAC layer or BlobFuse2 itself.

This is a manual, human-run check (consistent with [`CLAUDE.md`'s no-live-deployment rule](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) — Claude doesn't run this against live Azure resources); it's referenced from [Migration / rollout notes](#migration--rollout-notes) as a sanity check before treating the demo as ready.

## Troubleshooting the mount with IMDS and curl (manual)

BlobFuse2 does its own token exchange against the VM's local IMDS endpoint internally — if the mount fails, it's useful to reproduce that exchange by hand to tell whether the problem is *underneath* BlobFuse2 (identity not attached, RBAC not propagated/wrong scope) or specific to BlobFuse2 itself (bad config, wrong `type`, missing packages). This follows the same Microsoft tutorial pattern for exercising a Linux VM's managed identity against Azure Storage ([Tutorial: Use a Linux VM/VMSS to access Azure resources](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/tutorial-linux-managed-identities-vm-access)) used to validate this plan originally, using nothing but `curl` (already present on any Ubuntu image — no new tooling):

1. **Get a token from the VM's local managed identity endpoint (IMDS)**, scoped to the storage resource:
   ```bash
   curl 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' -H Metadata:true
   ```
   A successful response is a JSON blob with an `access_token` field — this alone confirms the VM's system-assigned managed identity is attached and Azure will issue it tokens, independent of BlobFuse2 entirely. Capture the token into a variable for the next steps:
   ```bash
   access_token=$(curl 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' -H Metadata:true | jq -r '.access_token')
   ```
   (`jq` may need installing — `sudo apt-get install -y jq` — or the token can be copied out of the raw JSON by hand.)
2. **Confirm read access to `rse-demo-container` works** via the Blob REST API's [List Blobs](https://learn.microsoft.com/en-us/rest/api/storageservices/list-blobs) operation, bypassing BlobFuse2 entirely:
   ```bash
   curl -i "https://<STORAGE ACCOUNT>.blob.core.windows.net/rse-demo-container?restype=container&comp=list" \
     -H "x-ms-version: 2021-08-06" \
     -H "Authorization: Bearer $access_token"
   ```
   Expect **`200 OK`**. **If this succeeds but the mount still won't come up, the problem is BlobFuse2-specific** (config file, installed package version, `type: block` vs the account's actual namespace mode) rather than identity/RBAC.
3. **Confirm the scope is as narrow as intended** — the same token against a second container on the same account:
   ```bash
   curl -i "https://<STORAGE ACCOUNT>.blob.core.windows.net/other-container?restype=container&comp=list" \
     -H "x-ms-version: 2021-08-06" \
     -H "Authorization: Bearer $access_token"
   ```
   and the account root, via the [List Containers](https://learn.microsoft.com/en-us/rest/api/storageservices/list-containers2) operation:
   ```bash
   curl -i "https://<STORAGE ACCOUNT>.blob.core.windows.net/?comp=list" \
     -H "x-ms-version: 2021-08-06" \
     -H "Authorization: Bearer $access_token"
   ```
   Both should come back **`403 Forbidden`**, proving the role assignment is genuinely scoped to `rse-demo-container` and not the whole account.
4. **Confirm read-only** via the [Put Blob](https://learn.microsoft.com/en-us/rest/api/storageservices/put-blob) operation:
   ```bash
   curl -i -X PUT "https://<STORAGE ACCOUNT>.blob.core.windows.net/rse-demo-container/test-blob.txt" \
     -H "x-ms-version: 2021-08-06" \
     -H "x-ms-blob-type: BlockBlob" \
     -H "Content-Length: 0" \
     -H "Authorization: Bearer $access_token"
   ```
   Expect **`403 Forbidden`**, confirming Storage Blob Data *Reader* (not *Contributor*) is what's actually granted server-side — independent of BlobFuse2's own `--read-only=true`.
5. If step 1 fails, the identity itself isn't attached or IMDS isn't reachable — a BlobFuse2 config change won't fix that. If step 2 (or the mount) fails but the token in step 1 was issued successfully, the likely causes are: the `RoleAssignment` hasn't propagated yet (a few minutes — the systemd unit's `Restart=on-failure` above exists precisely for this), the `scope` ended up account-wide rather than container-scoped (see [Open questions](#open-questions--assumptions-to-confirm-before-implementing)), or the wrong role definition ID was used.

This is a manual, human-run check (consistent with [`CLAUDE.md`'s no-live-deployment rule](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) — Claude doesn't run this against live Azure resources).

## Secrets and config

- **The storage account key (`storage_account_primary_key`) keeps being exported as a secret stack output**, unchanged from today — it's no longer part of the VM's own access path, but is kept specifically for **management purposes**: an operator managing the storage account directly (e.g. via `az`, or VS Code's/Storage Explorer's own Azure AD sign-in or the key — see [Design principles](#design-principles)) outside of what the VM's managed identity is scoped to do.
- **No new secrets introduced** for the VM's own storage access. Managed identity tokens are issued and rotated by Azure automatically; nothing new is generated by Pulumi or stored in state for that path. The BlobFuse2 config file itself (rendered into `custom_data`, which is not treated as secret today) contains only the storage account name and container name — no key, SAS, or other credential.

## Testing plan

Extending the existing `pulumi.runtime.set_mocks`-based suite (mirroring the module layout per [`01-the-scenario.md`](01-the-scenario.md#module-layout)):

- `tests/test_compute.py` — assert the VM resource's `identity.type` is `SystemAssigned`; decode the rendered `custom_data` and assert it references the BlobFuse2 install step, contains `mode: msi` and `rse-demo-container` in the rendered config, contains `--read-only=true` and `--foreground=true` in the systemd unit's `ExecStart`, contains `disable-kernel-cache: true` and an `attr_cache.timeout-sec: 0`, and does **not** contain the storage account key or any other credential-shaped value anywhere in the payload; assert the `authorization.RoleAssignment` (defined here, not in `infra/storage.py` — see [Changes by resource](#changes-by-resource)) is scoped to `blob_container.id` (not the storage account), with the Storage Blob Data **Reader** role definition ID, and `principal_type=ServicePrincipal`.
- `tests/test_storage.py` — assert `storage_account_primary_key`/the underlying key export is still present (i.e. no regression removing the management-purpose export); no RBAC assertions here, since the role assignment lives in `infra/compute.py`.
- Per [`01-the-scenario.md`'s testing plan](01-the-scenario.md#testing-plan), the earlier scenario's tests deliberately didn't assert on identity/RBAC presence, since that posture was out of scope then — this iteration is where those tests get added, per that document's own note.
- Still no live Azure calls, and no live mount attempt — `MockResourceArgs`/`MockCallArgs`, run via `uv run pytest`, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature). Whether the mount actually comes up is verified live only by the human running [Verifying the mount](#verifying-the-mount-manual) above.

## Migration / rollout notes

- This is not a from-scratch resource — it changes an **existing, potentially-already-deployed** stack. `identity` on an existing VM and a new `RoleAssignment` are additive changes Pulumi can apply in place — but the cloud-init content inside `custom_data` does change (the new BlobFuse2 install/config/mount steps), which **does** force a VM replace under the existing `replace_on_changes=["osProfile.customData"]` policy — worth calling out explicitly to whoever runs the deploy, same as the equivalent note in [`03-managing-identity-database.md`](03-managing-identity-database.md#migration--rollout-notes).
- Order of operations for a human running this (not Claude, per [`CLAUDE.md`](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature)):
  1. `pulumi up` to create (or replace) the VM with its identity, the role assignment, and the new cloud-init mount steps.
  2. The mount comes up on its own during first boot via the systemd unit — no separate manual script is needed here, unlike the database plan's role-membership script. If the VM's very first boot races ahead of RBAC propagation, the unit's `Restart=on-failure` retries automatically.
  3. From an RDP/SSH session on the VM, run through [Verifying the mount](#verifying-the-mount-manual) — or, if that doesn't come up cleanly, [Troubleshooting the mount with IMDS and curl](#troubleshooting-the-mount-with-imds-and-curl-manual) — to confirm the managed identity + RBAC grant work as expected before treating the demo as ready.
  4. Open `/mnt/rse-demo-container` directly (in VS Code, a terminal, or a file manager) — no "Attach Storage Account..." step and no Azure sign-in needed for the VM's own access.
  5. The storage account key stays exported and in place throughout — it's kept deliberately, for management, not something to revoke or rotate as part of this rollout.

## Out of scope (still deferred)

Per [`01-the-scenario.md`'s planned follow-up](01-the-scenario.md#planned-follow-up-later-iteration-not-part-of-this-scenario), this iteration is identity/RBAC only. Still deferred to later iterations:

- VNet-integrated / private database access (service endpoints or private link) and removing the `0.0.0.0`–`255.255.255.255` SQL firewall rule — see [`03-managing-identity-database.md`](03-managing-identity-database.md).
- Narrowing the NSG's SSH/RDP rules to a trusted IP range instead of `Internet`/`0.0.0.0/0`.
- SSH key authentication on the VM instead of password auth (VM login is unrelated to the resource-access identity work here).
- Azure Bastion or another jump-host pattern instead of a directly internet-facing VM.
- **RBAC for human/operator access to the resource group** (e.g. moving off a subscription-level Owner/Contributor grant to a resource-group-scoped role). This iteration only scopes the VM's own access; who can manage the deployment's Azure resources is not addressed here.
- Write access through the mount, and ADLS Gen2/hierarchical-namespace accounts (`type: adls` in the BlobFuse2 config) — the current account is flat-namespace `StorageV2`, and the goal is read-only regardless.
- Tuning BlobFuse2's *file content* caching behaviour (`file_cache.timeout-sec`, switching to streaming/`block_cache` mode, cache eviction) beyond the defaults used here — not relevant for a small, mostly-static demo container. (This is distinct from `disable-kernel-cache`/`attr_cache.timeout-sec`, which aren't a performance tuning choice here — see the note under [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2).)

## Open questions / assumptions to confirm before implementing

1. **Does container-scoped `RoleAssignment` actually work for Storage Blob Data Reader as expected** (`scope=blob_container.id`)? Worth a final check against current Azure RBAC docs at implementation time — container-scoped assignments are supported for this role, but it's the kind of detail worth confirming rather than assuming, per this repo's existing convention (cf. `01-the-scenario.md`'s open questions on Public IP SKU retirement). [Verifying the mount](#verifying-the-mount-manual) (step 4) and [Troubleshooting with IMDS and curl](#troubleshooting-the-mount-with-imds-and-curl-manual) (step 3) above are exactly how to confirm this once deployed.
2. **Does the systemd unit's `After=network-online.target` reliably guarantee IMDS itself is reachable at that point in boot**, or can BlobFuse2's very first mount attempt still race ahead of it on a freshly-created VM? `Restart=on-failure`/`RestartSec=15` (see [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2)) is meant to absorb this, but it's worth confirming in practice that a transient first-boot failure does actually recover on its own rather than needing a manual `systemctl restart`.
3. **Which BlobFuse2/`fuse3` package versions does the `packages.microsoft.com` Ubuntu 22.04 (jammy) repo actually resolve to at implementation time**, and do they support every config key used above (`mode: msi`, root-level `allow-other`, the `--read-only=true` mount flag)? These were confirmed against BlobFuse2's current upstream docs and sample configs while drafting this plan, but package versions and config schemas do move — worth a quick `blobfuse2 --version` / `blobfuse2 mount --help` sanity check against whatever version actually installs. **Partially resolved during implementation**: Ubuntu 22.04's `fuse3` apt package ships a libfuse older than 3.16.1, which is old enough that BlobFuse2 logs a `disabling kernel-list-cache` compatibility warning at startup — harmless (see step 1 of [Verifying the mount](#verifying-the-mount-manual)), but a sign that package-version mismatches between `blobfuse2` and the distro's `fuse3` are real and worth expecting, not just a theoretical concern.
4. **Resolved during implementation: `Type=simple` requires `--foreground=true`, or the unit reports `inactive` instead of `active (running)`.** `blobfuse2 mount` daemonizes by default (forks into the background once mounted, and the invoking process exits); without `--foreground=true`, systemd's `Type=simple` tracks that exiting invoker rather than the actual mount, so `systemctl status` shows a clean `inactive` exit with no error, and the mount doesn't reliably stay up. Caught by actually deploying and observing `systemctl status blobfuse2-rse-demo-container.service` report `inactive` — see the note under [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2).
5. **Resolved during implementation: a successfully mounted, `active (running)` container listed as empty even though blobs existed in it.** With the `--foreground=true` fix above applied, the next observation was `/mnt/rse-demo-container` mounting cleanly but `ls` showing nothing. Root cause: neither the kernel's own dentry/attribute cache nor BlobFuse2's `attr_cache` (which this plan hadn't overridden, so it ran at BlobFuse2's default timeout) knew that the container's contents could change from *outside* BlobFuse2 — which they deliberately can, via the retained account key. Fixed by adding `disable-kernel-cache: true` and `attr_cache.timeout-sec: 0` to the BlobFuse2 config, per Microsoft's own guidance for this exact situation — see the note under [Mounting the container with BlobFuse2](#mounting-the-container-with-blobfuse2). Worth re-confirming after redeploying: with the fix in place, a file added to the container via the account key/Portal while the mount is already up should appear in `ls -la /mnt/rse-demo-container` without needing to remount or reboot.
