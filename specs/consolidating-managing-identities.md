# Consolidating Managing Identities — PR #8

Plan to bring [PR #8 "Access the storage container via managed identity (BlobFuse2 mount)"](https://github.com/alan-turing-institute/rse-cloud-cybersecurity/pull/8) (branch `01-managing-identity`) into `consolidation`, so the resulting branch still passes the project's verification gate (`ruff check`, `ruff format --check`, `ty check`, `pytest` — see [`CLAUDE.md`](../CLAUDE.md)), without breaking the Bastion, Log Analytics, Application Firewall, and Storage Firewall work already on `consolidation` ([`consolidating-bastion.md`](consolidating-bastion.md), [`consolidating-logs.md`](consolidating-logs.md), [`consolidating-firewall.md`](consolidating-firewall.md), [`consolidating-storage-firewall.md`](consolidating-storage-firewall.md)).

**Unlike PR #9's storage-firewall consolidation, the textual merge itself is not clean.** `git merge-tree` reports real conflict markers in `infra/__init__.py` and `infra/compute.py` — and, more importantly, a plain merge of both sides' code would produce a genuine Python circular import (`infra/storage.py` → `infra/compute.py` → `infra/storage.py`), because `consolidating-storage-firewall.md`'s own follow-up work independently added a managed-identity RBAC grant for VM storage access, in the *opposite* direction PR #8 assumed when it was designed. On top of that, both branches now grant the VM's identity overlapping access to the same blob container via two different role assignments — one already on `consolidation`, one added by PR #8 — which would silently defeat PR #8's whole "read-only, single-container, least-privilege" design goal if both landed unexamined. See "The compatibility problems" below before anything else.

## Starting point

- `consolidation`'s current tip (`22fb7e8`) has PR #3 (Bastion), PR #5 (Log Analytics), PR #7 (Application Firewall), and PR #9 (Storage Firewall) folded in, plus four follow-on commits from the storage-firewall consolidation's own fallout:
  - `858503c` — installs the Azure CLI on the VM via cloud-init, and allows its sign-in endpoints through the Application Firewall.
  - `06d3c8a` — switches that `az login` guidance to `--use-device-code` (plain `az login`'s sign-in page rendered blank behind the firewall).
  - `a13b424` — fixes `README-Storage.md`'s guidance to not run `pulumi stack output` on the VM (Pulumi isn't installed there).
  - `dde1215` — populates the shared "blob" private DNS zone with the storage endpoint's own record (without it, the VM couldn't resolve the storage account's name at all).
  - `22fb7e8` — **replaces that device-code human login with the VM's own system-assigned managed identity**: adds `identity=compute.VirtualMachineIdentityArgs(type=SYSTEM_ASSIGNED)` to `virtual_machine` (`infra/compute.py`), and a new `authorization.RoleAssignment` (`vm_storage_blob_data_contributor`, in `infra/storage.py`) granting that identity **Storage Blob Data Contributor** on the **whole storage account**, so `az login --identity` + `az storage blob upload/download --auth-mode login` works with no manual RBAC step and no interactive sign-in.
- `01-managing-identity` (`250fc46`) branches from `f4987d8` — the same pre-Bastion/Log-Analytics/Firewall/Storage base the other four sibling branches diverged from. It predates all of the above; its own design doc (`specs/02-managing-identity-storage.md`, brought in by this PR) was written and verified against a VM with no managed identity, no Application Firewall, and no storage-account network ACL yet.
- `git merge-tree $(git merge-base consolidation origin/01-managing-identity) consolidation origin/01-managing-identity` shows **conflict markers** in `infra/__init__.py` (the re-export list) and `infra/compute.py` (the module docstring, the `pulumi_azure_native` import line, and the block right after `virtual_machine` is created). `infra/templates/vm-cloud-init.yaml.j2` merges cleanly (both sides only append, at different points in the file). `infra/templates/blobfuse2-config.yaml.j2`, `infra/templates/blobfuse2.service.j2`, and `specs/02-managing-identity-storage.md` are added cleanly (untouched by anything else on `consolidation`).

## What PR #8 changes

- Adds a system-assigned managed identity to `virtual_machine` (`infra/compute.py`) — `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)`.
- Adds `storage_blob_data_reader_role_assignment`, an `authorization.RoleAssignment` granting that identity **Storage Blob Data Reader** (read-only), scoped to `blob_container.id` (the `rse-demo-container` container specifically, not the whole storage account). Deliberately placed in `infra/compute.py`, not `infra/storage.py` — PR #8's own reasoning (see `specs/02-managing-identity-storage.md`'s "Changes by resource") is that `infra/compute.py` needs to import `storage_account`/`blob_container` from `infra/storage.py` for the BlobFuse2 config below, so `infra/storage.py` importing `virtual_machine` back "would be a genuine Python circular import, not just a style question."
- Mounts `rse-demo-container` directly on the VM's filesystem at `/mnt/rse-demo-container` via **BlobFuse2**, authenticating with `mode: msi` (the managed identity, via the VM's local IMDS endpoint) — no account key, SAS, or other credential anywhere in the config:
  - New cloud-init steps in `infra/templates/vm-cloud-init.yaml.j2`: install `fuse3`/`blobfuse2` from `packages.microsoft.com` (via `packages-microsoft-prod.deb`, Microsoft's generic installer for that feed), enable `user_allow_other` in `/etc/fuse.conf`, create the mount point/config/cache directories, write the rendered config and systemd unit, `daemon-reload` + `enable --now` the unit.
  - New template `infra/templates/blobfuse2-config.yaml.j2` (`type: block`, `disable-kernel-cache: true`, `attr_cache.timeout-sec: 0` — needed because the account's retained key lets blobs be added outside BlobFuse2 entirely, per the template's own comment).
  - New template `infra/templates/blobfuse2.service.j2` (`Type=simple` with `--foreground=true` — required, or the daemonizing `blobfuse2 mount` process exits and systemd reports `inactive`; `--read-only=true`; `Restart=on-failure`/`RestartSec=15`, absorbing RBAC-propagation delay on first boot).
  - `infra/compute.py`'s `_custom_data`/`custom_data` grow a third input, `storage_account.name`, to render the BlobFuse2 config.
- Adds `specs/02-managing-identity-storage.md`: a detailed design doc (goals, design principles, a manual verification procedure using `systemctl`/`ls`/`touch`, and a `curl`+IMDS-token troubleshooting procedure that deliberately checks for `403 Forbidden` on write attempts and on other containers, to prove the Reader role and container scope are both actually enforced).
- Extends `tests/test_compute.py` (VM has a `SystemAssigned` identity; the rendered `custom_data` contains the BlobFuse2 install/config/unit content and no credential; the role assignment is scoped to `blob_container.id` with the Reader role ID and `ServicePrincipal` principal type) and `tests/conftest.py` (mocks the `azure-native:authorization:getClientConfig` call PR #8's `role_definition_id` construction uses).

## The compatibility problems

### 1. A genuine circular import, not just a merge conflict

`consolidation`'s `22fb7e8` already added a VM-identity-to-storage RBAC grant — independently, for a different reason (the `az storage blob upload/download` CLI workflow) — and placed it in `infra/storage.py`, importing `virtual_machine` from `infra/compute.py` (`storage → compute`). PR #8 needs the opposite direction: `infra/compute.py` importing `storage_account`/`blob_container` from `infra/storage.py`, for the BlobFuse2 mount config, with its own role assignment placed in `infra/compute.py` specifically to avoid a cycle "since `infra/storage.py` must stay free of importing this module back" (its own words, in `specs/02-managing-identity-storage.md`'s "Changes by resource"). Merging both untouched creates `storage.py → compute.py → storage.py` — not a stylistic clash, an `ImportError` the moment either module is imported.

**Fix applied in this plan:** adopt PR #8's direction as the one direction. Move the existing `vm_storage_blob_data_contributor` role assignment (and its `_STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID` constant) out of `infra/storage.py` and into `infra/compute.py`, right after `virtual_machine` — the same place PR #8 puts its own role assignment, and for the same reason. `infra/storage.py` drops its `from infra.compute import virtual_machine` import and its now-unused `authorization` import entirely; nothing in `infra/storage.py` depends on `infra/compute.py` any more. This also resolves problem 2 below, since it means there's exactly one role assignment to place, not two.

### 2. Two overlapping RBAC grants on the same identity would silently defeat PR #8's least-privilege goal

- `consolidation`'s existing grant: **Storage Blob Data Contributor**, scoped to `storage_account.id` — the *whole account*, read **and** write.
- PR #8's new grant: **Storage Blob Data Reader**, scoped to `blob_container.id` — one container, read-only.

Azure RBAC grants are additive: if both land, the VM's identity ends up with the *union* — which is exactly the broader, account-wide, read-write grant that already exists. The narrower Reader-on-one-container assignment becomes inert: it grants nothing the Contributor-on-the-account assignment didn't already cover. That's not just redundant, it's actively misleading, because PR #8's own manual verification procedure (`specs/02-managing-identity-storage.md`, "Verifying the mount" step 3 and "Troubleshooting the mount with IMDS and curl" steps 3–4) is built entirely around confirming this identity **cannot** write to the container or read any other container — `touch` inside the mount expecting `Permission denied`, and raw `curl` `PUT`/list calls against the container and the account root expecting `403 Forbidden`. With the existing Contributor-on-the-account grant still in place, every one of those checks would unexpectedly **succeed** (the write would go through, the other container would list), and nothing in the merged code would explain why — a live-verification trap left for whoever runs it, not a documentation nitpick.

**This plan resolves it by keeping a single role assignment, not two — narrowed in scope but not in role level:** keep the existing `vm_storage_blob_data_contributor` (Contributor, needed for the already-shipped `az storage blob upload/download --auth-mode login` CLI workflow in `README-Storage.md`, which needs write access), but change its `scope` from `storage_account.id` to `blob_container.id`. `rse-demo-container` is the only container either workflow — the CLI path or the BlobFuse2 mount — ever touches, so this is a genuine tightening (account-wide → single-container) even though it keeps write capability PR #8's original Reader-only design didn't have.

**The trade-off, made explicit rather than left implicit:** this is *not* the same posture PR #8 designed and tested for. BlobFuse2's own `--read-only=true` mount flag still stops writes through the mount itself, but the RBAC layer underneath no longer independently backs that up (an identity holding Contributor could still write via the CLI path, bypassing the mount's read-only flag). PR #8's `specs/02-managing-identity-storage.md` needs updating to say so plainly, and its `touch`/`curl -X PUT` verification steps need updating to expect success (proving *the mount's* read-only flag, not the RBAC layer) rather than `403`/`Permission denied` — see step 8 below. Restoring true RBAC-backed read-only defense-in-depth (e.g. a second, narrower identity or role dedicated to the mount, separate from whatever needs write) is flagged as a future call in "Out of scope for this document", not attempted here, consistent with how `consolidating-storage-firewall.md` already leaves the now-unexercised `AllowAzureStorage` firewall rule in place rather than removing it.

### 3. BlobFuse2's `packages-microsoft-prod.deb` install alongside the existing manual `packages.microsoft.com` apt sources

The VM's cloud-init already registers `packages.microsoft.com` twice, manually (a GPG key + a `.sources` file each, for the VS Code and Azure CLI repos — see `infra/templates/vm-cloud-init.yaml.j2`, added by `858503c`/pre-existing scenario work). PR #8 registers the same host a third way, via Microsoft's generic `packages-microsoft-prod.deb` installer (its own GPG key import + its own `apt` source file, for a different repo path — the Ubuntu "jammy" `blobfuse2`/`fuse3` feed). These target different repo paths under the same host, so `apt` handling three separate source entries for `packages.microsoft.com` is expected to be harmless — but it hasn't been exercised together on a real VM, and a duplicate-key or duplicate-source warning during `apt-get update` (not necessarily a failure) is plausible. Flagged for the manual `pulumi up` verification (step 8 below) to actually check, rather than assumed clean; not a blocker to merging.

### 4. BlobFuse2's `mode: msi` needs no Application Firewall change — worth stating, not assuming

Per `README-Firewall.md`'s existing "Consolidation note (managed identity)", `az login --identity` bypasses the Application Firewall's `0.0.0.0/0` route entirely, because it talks to the VM's local Instance Metadata Service (`169.254.169.254`), which — like the platform DNS server — is exempt from that route. BlobFuse2's `mode: msi` does the same token exchange against the same IMDS endpoint (this is exactly what `specs/02-managing-identity-storage.md`'s own `curl`-against-IMDS troubleshooting section relies on). So no new Application Firewall rule is needed for the mount to authenticate — but nothing currently says so next to the existing IMDS note, and a reader could reasonably assume BlobFuse2 needs the same allow-list treatment `AllowAzureCli` gives interactive sign-in. Worth a one-line addition to `README-Storage.md` (step 7 below) rather than left to be independently rediscovered.

### 5. The VM gets replaced, again

`compute.VirtualMachine` already has `replace_on_changes=["osProfile.customData"]` (Azure ignores in-place `customData` updates, so this forces a delete-and-recreate whenever the cloud-init content changes). PR #8's new BlobFuse2 cloud-init steps change `custom_data`, so this merge forces another VM replace on top of whatever the storage-firewall consolidation's own cloud-init changes (`858503c`) already forced — expected, not a bug, but worth calling out plainly in the manual-verification steps (step 9) since it's a real interruption to the running demo VM, not a free/instant update.

## Steps

1. **Merge, expect conflicts.** From `consolidation`:
   ```sh
   git merge origin/01-managing-identity
   ```
   Expect conflicts in exactly `infra/__init__.py` and `infra/compute.py` (per the `git merge-tree` check above); everything else (`infra/templates/vm-cloud-init.yaml.j2`, the two new BlobFuse2 templates, `specs/02-managing-identity-storage.md`) should auto-merge cleanly. Resolve both conflicted files by hand per steps 2–4 below — don't take either side wholesale.

2. **Resolve `infra/storage.py`: remove the role assignment and its now-unneeded imports** (see problem 1). Delete the `vm_storage_blob_data_contributor` block, the `_STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID` constant, the `from infra.compute import virtual_machine` import, and the `authorization` import (`from pulumi_azure_native import authorization, network, storage` → `from pulumi_azure_native import network, storage`) from `infra/storage.py`. Nothing else in that file changes — `storage_subnet`, `storage_account`, `blob_container`, the private endpoint, and the private DNS zone group all stay exactly as they are on `consolidation`.

3. **Resolve `infra/compute.py`: merge the docstring, add the BlobFuse2 mount, and place the (single, re-scoped) role assignment here.**
   - Docstring: keep `consolidation`'s existing docstring (the Azure-CLI/`az login --identity` explanation, the Application-Firewall/network-ACL context) and fold in PR #8's BlobFuse2-mount summary, e.g.:
     ```python
     """Linux virtual machine reachable over RDP with a graphical desktop.

     VS Code, with the mssql extension, is the way to reach the SQL database (see
     specs/01-the-scenario.md - no managed identity/RBAC for the database yet).
     The Azure CLI is also installed (see below) and is the way to reach the
     storage account for uploads/downloads, signed in as this VM's own
     system-assigned identity (`identity=` below) via `az login --identity` -
     its own VS Code extension (also installed, for completeness) no longer
     works once the Application Firewall and the storage account's own network
     rules are in place. The same identity also mounts `rse-demo-container`
     directly on the VM's filesystem via BlobFuse2 (`mode: msi`,
     specs/02-managing-identity-storage.md) for read/browse access with no
     sign-in step at all. See `vm_storage_blob_data_contributor` below for the
     single RBAC grant behind both paths, and README-Storage.md for how each is
     used from the VM.
     ...
     """
     ```
   - Imports: add `authorization` to the existing `from pulumi_azure_native import compute, monitor` line, and add `from infra.storage import blob_container, storage_account` alongside the existing `infra.database`/`infra.monitoring`/`infra.networking`/`infra.resource_group` imports.
   - Add the two new template paths/constants (`_BLOBFUSE2_CONFIG_TEMPLATE_PATH`, `_BLOBFUSE2_UNIT_TEMPLATE_PATH`, `_BLOBFUSE2_MOUNT_PATH`, `_BLOBFUSE2_CONFIG_PATH`, `_BLOBFUSE2_SERVICE_NAME`) and the two new `jinja2.Template(...)` instances, exactly as PR #8 defines them.
   - Extend `_custom_data`/`custom_data` to take and render `storage_account_name` (PR #8's version, verbatim) — `custom_data = pulumi.Output.all(sql_server.fully_qualified_domain_name, sql_database.name, storage_account.name).apply(...)`.
   - `virtual_machine = compute.VirtualMachine(...)`: keep `consolidation`'s `diagnostics_profile=compute.DiagnosticsProfileArgs(boot_diagnostics=...)` and its existing `identity=compute.VirtualMachineIdentityArgs(type=compute.ResourceIdentityType.SYSTEM_ASSIGNED)` (both sides add the identical `identity=` block — keep the one already there, don't duplicate it).
   - Right after `virtual_machine`, and before the existing Log-Analytics extension/DCR-association block, add the **single, re-scoped** role assignment (see problem 2):
     ```python
     # Grants the VM's own system-assigned managed identity data-plane access
     # to rse-demo-container - scoped to that one container, not the whole
     # storage account, so nothing else on the account is in reach. Backs
     # both `az storage blob upload/download --auth-mode login` (needs
     # write, hence Contributor not Reader - see
     # specs/consolidating-managing-identities.md) and the BlobFuse2 mount
     # below (whose own --read-only=true mount flag is what actually keeps
     # the mount read-only; this grant itself is not read-only).
     # principal_type is set explicitly because the managed identity is
     # created in this same deployment; without it, Azure AD replication lag
     # between creating the identity and creating this role assignment can
     # make the assignment fail validation.
     vm_storage_blob_data_contributor = authorization.RoleAssignment(
         "rse-vm-storage-blob-data-contributor",
         principal_id=virtual_machine.identity.principal_id,
         principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL,
         role_definition_id=pulumi.Output.concat(
             resource_group.id,
             "/providers/Microsoft.Authorization/roleDefinitions/",
             _STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID,
         ),
         scope=blob_container.id,
     )
     ```
     (`_STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"` — the same constant moved from `infra/storage.py`, unchanged.) This keeps `resource_group.id`-based `role_definition_id` construction (the pattern already on `consolidation`) rather than introducing PR #8's `authorization.get_client_config_output().subscription_id` pattern — both are valid, and reusing the existing one means no new `tests/conftest.py` mock is needed (see step 6).

4. **Resolve `infra/__init__.py`.** Combine both sides' re-exports and `__all__` entries — nothing is dropped, `vm_storage_blob_data_contributor` just moves from the `infra.storage` import to the `infra.compute` import:
   ```python
   from infra.compute import (
       virtual_machine,
       vm_admin_password,
       vm_storage_blob_data_contributor,
   )
   ...
   from infra.storage import (
       blob_container,
       storage_account,
       storage_account_private_dns_zone_group,
       storage_account_private_endpoint,
       storage_subnet,
   )
   ```
   `__all__` keeps every existing entry (alphabetical, matching the file's existing ordering) — `vm_storage_blob_data_contributor` stays in the list, just conceptually now "from compute". No change to `__main__.py` — this consolidation adds no new stack outputs.

5. **Bring in the cloud-init/template changes as-is.** `infra/templates/vm-cloud-init.yaml.j2` should auto-merge cleanly (confirm with `git status`/no conflict markers); `infra/templates/blobfuse2-config.yaml.j2` and `infra/templates/blobfuse2.service.j2` are added new, unchanged from PR #8.

6. **Close the test coverage gap and adjust for the re-scoped role.**
   - In `tests/test_storage.py`: remove `test_vm_storage_role_assignment_grants_data_contributor_on_the_storage_account` (the role assignment no longer lives here) and drop the now-unused `virtual_machine`/`vm_storage_blob_data_contributor` imports.
   - In `tests/test_compute.py`: add PR #8's `test_virtual_machine_has_system_assigned_identity` and `test_custom_data_mounts_the_storage_container_with_blobfuse2` (verbatim — these don't depend on the role assignment's scope/role level). Add a replacement for the role-assignment test, moved from `test_storage.py` and updated for the new scope, importing `blob_container` alongside the existing `virtual_machine`:
     ```python
     @pulumi.runtime.test
     def test_vm_storage_role_assignment_grants_data_contributor_on_the_container(self):
         def check(args: tuple) -> None:
             (
                 principal_id,
                 principal_type,
                 role_definition_id,
                 scope,
                 vm_principal_id,
                 blob_container_id,
             ) = args
             self.assertEqual(principal_id, vm_principal_id)
             self.assertEqual(principal_type, "ServicePrincipal")
             self.assertIn("ba92f5b4-2d11-453d-a403-e96b0029c9fe", role_definition_id)
             self.assertEqual(scope, blob_container_id)

         return pulumi.Output.all(  # ty: ignore[missing-argument]
             vm_storage_blob_data_contributor.principal_id,
             vm_storage_blob_data_contributor.principal_type,
             vm_storage_blob_data_contributor.role_definition_id,
             vm_storage_blob_data_contributor.scope,
             virtual_machine.identity.principal_id,
             blob_container.id,
         ).apply(check)  # ty: ignore[invalid-argument-type]
     ```
   - **Do not** add PR #8's own `storage_blob_data_reader_role_assignment`-scoped test or its `tests/conftest.py` `getClientConfig` mock — that resource doesn't exist in this merged design (see problem 2/step 3's `role_definition_id` choice), so both would reference a name that was never created.
   - Run the full suite in a disposable worktree before treating this as done, same as every prior consolidation.

7. **Update documentation.**
   - `specs/02-managing-identity-storage.md` (brought in by the merge): add a short "Consolidation note" near the top, matching `README-Storage.md`'s existing style, saying:
     - The role assignment is **Storage Blob Data Contributor at container scope**, not Storage Blob Data Reader — it's the same grant `consolidation`'s storage-firewall follow-up already added for the `az storage blob upload/download` CLI workflow, narrowed from account-wide to `rse-demo-container` rather than duplicated (see `specs/consolidating-managing-identities.md`, "The compatibility problems" #2).
     - Update "Design principles", "Changes by resource", "Verifying the mount" (step 3's `touch` check now expects the write to **succeed**, since the RBAC layer permits it — only BlobFuse2's own `--read-only=true` mount flag stops it, so the check becomes "confirm the *mount* refuses the write, not the identity"), and "Troubleshooting the mount with IMDS and curl" (steps 3–4's `curl` calls against other containers/the account root and the `PUT` call now expect success too, for the same reason) to match. Cross-reference this document rather than duplicating the reasoning.
   - `README-Storage.md`: extend "Accessing the storage account from the virtual machine" with a short new subsection on the BlobFuse2 mount (`/mnt/rse-demo-container`, browsable directly with no sign-in step), noting it shares the same `vm_storage_blob_data_contributor` grant as the CLI workflow above it (now container-scoped) and that `mode: msi` reaches the VM's IMDS endpoint the same way `az login --identity` does — no Application Firewall change needed (problem 4 above).
   - `README-Firewall.md`: extend the existing "Consolidation note (managed identity)" to mention BlobFuse2's `mode: msi` alongside `az login --identity` as another IMDS-based path that needs no firewall rule.
   - `README.md`: update the `storage.py` bullet under "Project structure" to say the role assignment now lives in `compute.py` (moved there to avoid the import cycle — see this plan), and add a `compute.py` bullet mention of the BlobFuse2 mount.

8. **Re-verify PR #8's own manual procedure against the re-scoped role**, updating `specs/02-managing-identity-storage.md` per step 7 rather than leaving its checklist silently wrong:
   - "Verifying the mount" step 3 (`touch` inside the mount) now demonstrates the **mount's** read-only flag, not an RBAC denial — expect `Permission denied` still (BlobFuse2 enforces `--read-only=true` regardless of the underlying role), but the doc's explanation of *why* needs to change from "enforced twice over... by the Storage Blob Data *Reader* role" to "enforced by the mount's `--read-only=true` flag; the underlying role is Contributor, shared with the CLI upload/download path".
   - "Troubleshooting... with IMDS and curl" steps 3–4 (raw `curl` against another container / the account root / a `PUT`) now genuinely succeed rather than 403 — the doc must say so, or whoever runs this will reasonably conclude the deployment is broken.

9. **Manual verification that the merge itself is correct.**
   ```sh
   git log --oneline -5                          # merge commit + "Access the storage container..." both present
   git status                                     # working tree clean, no leftover conflict markers
   grep -rn "^<<<<<<<\|^=======\|^>>>>>>>" --include='*.py' .   # no unresolved conflict markers
   git diff origin/01-managing-identity consolidation -- infra/compute.py infra/storage.py infra/__init__.py
                                                   # should show only this plan's re-scoping/relocation, not a lost feature
   ```

10. **Manual verification that the Pulumi program actually implements this end-to-end.** Per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature), `pulumi preview`/`pulumi up` are **run by the user, not Claude** — unit tests and static checks are as far as automated verification goes here.
    - `pulumi preview` first — expect the VM to be **replaced** (cloud-init content changes again, on top of the storage-firewall consolidation's own replace — see problem 5), `vm_storage_blob_data_contributor` to be **replaced** (its `scope` changes from the storage account to the container — not an in-place update), and the two new templates/role assignment to otherwise apply cleanly.
    - `pulumi up`, then from an RDP session on the VM: run `apt-get update` and confirm no fatal error from the third `packages.microsoft.com` registration (problem 3) alongside the existing two; run `specs/02-managing-identity-storage.md`'s "Verifying the mount" procedure (`systemctl status blobfuse2-rse-demo-container.service`, `ls -la /mnt/rse-demo-container`, `touch` — expect `Permission denied` from the mount flag) and confirm `az storage blob upload/download --auth-mode login` (from `README-Storage.md`) still works, proving one role assignment now backs both paths.
    - Confirm (per the updated troubleshooting section, step 8 above) that a raw `curl` `PUT` and a listing of a *different* container both now **succeed** rather than `403` — proving this plan's trade-off (Contributor-at-container-scope, not Reader) is what's actually deployed, not a leftover assumption from PR #8's original design.

## Verification checklist

- [ ] `git merge origin/01-managing-identity` completes, with conflicts in exactly `infra/__init__.py` and `infra/compute.py`, both resolved per steps 2–4.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes, including the new/moved tests in `tests/test_compute.py` and the removal of the stale role-assignment test from `tests/test_storage.py`.
- [ ] `infra/storage.py` no longer imports anything from `infra/compute.py`, and no longer defines any `authorization.RoleAssignment`.
- [ ] `infra/compute.py` defines exactly **one** `authorization.RoleAssignment` (`vm_storage_blob_data_contributor`), scoped to `blob_container.id`, role Storage Blob Data **Contributor** — PR #8's separate `storage_blob_data_reader_role_assignment` does not exist in the merged code.
- [ ] `infra/compute.py`'s `custom_data` renders the BlobFuse2 config/unit and installs `fuse3`/`blobfuse2` via cloud-init.
- [ ] `infra/__init__.py` re-exports `vm_storage_blob_data_contributor` from `infra.compute`, not `infra.storage`.
- [ ] `specs/02-managing-identity-storage.md`'s "Design principles"/"Changes by resource"/verification sections reflect Contributor-at-container-scope, not Reader, and its `touch`/`curl` checks expect the corrected outcomes.
- [ ] `README-Storage.md`, `README-Firewall.md`, and `README.md` reflect the BlobFuse2 mount, the single shared role assignment, and the IMDS/no-firewall-change note.
- [ ] (Manual, by the user) `git log`/`git status`/the targeted `git diff` in step 9 confirm the merge captured every file PR #8 touches, with no leftover conflict markers.
- [ ] (Manual, by the user) `pulumi preview`/`pulumi up` succeed against the `dev` stack; the VM and the role assignment both show as replaced, not merely updated.
- [ ] (Manual, by the user) The BlobFuse2 mount comes up (`active (running)`) and `/mnt/rse-demo-container` is browsable; `az storage blob upload/download --auth-mode login` still works via the same identity.
- [ ] (Manual, by the user) A write attempt through the mount is refused (by the mount flag); a raw `curl`/CLI write or cross-container read via the identity's token succeeds (by the RBAC grant) — confirming the documented trade-off, not a silent gap.

## Out of scope for this document

- Restoring true RBAC-backed read-only/least-privilege for the BlobFuse2 mount specifically (e.g. a second, narrower identity or role dedicated only to the mount, separate from whatever needs write access via the CLI) — this plan deliberately keeps one shared Contributor-at-container-scope grant instead, per "The compatibility problems" #2, and flags the trade-off rather than solving it. A future iteration could revisit this if the CLI upload/download workflow and the mount's access needs are ever meant to diverge.
- Database access via managed identity, VNet segmentation, NSG narrowing, SSH-key auth, or RBAC for human/operator access to the resource group — all already flagged as deferred in `specs/01-the-scenario.md`'s "Planned follow-up" section and in PR #8's own `specs/02-managing-identity-storage.md`'s "Out of scope (still deferred)".
- Removing the storage account's retained primary key/its stack output — PR #8 and the existing storage-firewall consolidation both keep it for human management purposes; unaffected by this plan.
- Chasing down whether the third `packages.microsoft.com` apt registration (problem 3) produces a benign warning or something worse — flagged for the manual verification in step 10, not resolved here without a live VM.
- Claude running `pulumi preview`/`pulumi up`, or the manual mount/RBAC verification procedures — per [CLAUDE.md](../CLAUDE.md), all of that is the user's to run (steps 8–10 above are written for the user to execute).
