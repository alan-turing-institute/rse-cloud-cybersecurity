# Consolidating Storage Firewall — PR #9

Plan to bring [PR #9 "Add Azure Storage firewall rules"](https://github.com/alan-turing-institute/rse-cloud-cybersecurity/pull/9) (branch `05-storage`) into `consolidation`, so the resulting branch still passes the project's verification gate (`ruff check`, `ruff format --check`, `ty check`, `pytest` — see [`CLAUDE.md`](../CLAUDE.md)), without breaking the Bastion, Log Analytics, and Application Firewall work already on `consolidation` ([`consolidating-bastion.md`](consolidating-bastion.md), [`consolidating-logs.md`](consolidating-logs.md), [`consolidating-firewall.md`](consolidating-firewall.md)).

**The textual merge itself is clean** — unlike the previous three consolidations, `git merge-tree` reports no conflicts at all: PR #9 only touches `infra/storage.py` (untouched by every other branch already on `consolidation`) and adds a new `README-Storage.md`. But a clean textual merge is not the same as a working one. Checked directly against what's already on `consolidation`, PR #9's storage subnet collides with an existing subnet's address range (a guaranteed `pulumi up` failure, not a silent one), and the storage account's network ACL locks the VM out of the storage account entirely. Unlike the CIDR collision, that second point is **accepted rather than patched around**: this plan deliberately relies on the `Microsoft.Storage` service endpoint mechanism PR #9 already introduces, extends it to the VM's own subnet, and accepts that the VM's documented VS Code Azure Storage extension workflow no longer works as a result — replaced with an Azure CLI–based workflow. See "The compatibility problems" below before anything else.

## Starting point

- `consolidation`'s current tip (`b3a5e8a`) has PR #3 (Bastion), PR #5 (Log Analytics), and PR #7 (Application Firewall) folded in.
- `05-storage` (`c25fbb1`) branches from `98b979f` — the same pre-Bastion/Log-Analytics/Firewall commit the other three branches diverged from.
- `git merge-tree $(git merge-base consolidation origin/05-storage) consolidation origin/05-storage` shows a clean auto-merge: `infra/storage.py` merges with no conflict markers (`consolidation` never touched it after the merge base), and `README-Storage.md` is added cleanly.
- That clean merge was checked against the rest of `consolidation`'s state (`infra/networking.py`, `infra/firewall.py`, `infra/__init__.py`) rather than assumed safe — see below for what that check found.

## What PR #9 changes

- Updates `infra/storage.py`:
  - Adds `storage_subnet`, a new `Subnet` (`10.0.5.0/24`) carrying a `Microsoft.Storage` service endpoint (required before the storage account can use IP/VNet-based firewall rules — see the Azure docs linked from `README-Storage.md`) and the VM's `network_security_group`.
  - Adds an `ip_rules` list allowing exactly one IP (`193.60.220.253`, the Turing VPN's public egress address).
  - Adds several `StorageAccount` hardening properties: `allow_blob_public_access=False`, `enable_https_traffic_only=True`, `minimum_tls_version=TLS1_2`, at-rest `encryption` (Microsoft-managed keys, blob + file), `is_hns_enabled=True` (Data Lake Gen2 hierarchical namespace), `enable_nfs_v3=True`, and a `network_rule_set` (`bypass=AZURE_SERVICES`, `default_action=DENY`, the `ip_rules` above, and a `virtual_network_rules` entry for `storage_subnet`).
  - Adds `storage_account_private_endpoint`, a `PrivateEndpoint` in `storage_subnet` targeting the storage account's `blob` group — demonstrates the private-link mechanism but isn't wired up with a private DNS zone (unlike the monitoring private endpoint in `infra/dns.py`), so nothing in the repo actually resolves to it yet; it's additive infrastructure, not something else depends on it.
- Adds `README-Storage.md`: a standalone write-up (mirrors `README-Bastion.md`/`README-LogAnalytics.md`/`README-Firewall.md`'s style), covering the firewall-rule/service-endpoint mechanism, the encryption settings, and how to generate a Storage Explorer SAS URL from an authorised IP.
- Adds **no tests** for any of this — `tests/test_storage.py` is untouched by PR #9.

## The compatibility problems

### 1. Subnet address collision with the firewall management subnet (hard failure)

PR #9's `storage_subnet` uses `10.0.5.0/24`. `infra/firewall.py` (already on `consolidation`) already created `firewall_management_subnet` on that exact range:

```python
firewall_management_subnet = network.Subnet(
    "AzureFirewallManagementSubnet",
    ...
    address_prefix="10.0.5.0/24",  # 64 address minimum
)
```

Two subnets with overlapping address ranges in the same VNet are rejected by Azure at creation time — this isn't a silent behavioural regression like the firewall consolidation's FQDN gap, it's a guaranteed `pulumi up` failure the moment both branches' subnets are deployed together. The VNet's other reserved ranges are `10.0.1.0/24` (`vm_subnet`), `10.0.2.0/24` (Bastion), `10.0.3.0/24` (monitoring private endpoint), and `10.0.4.0/24` (`firewall_subnet`), so `10.0.6.0/24` is the next free `/24`.

**Fix applied in this plan:** change `storage_subnet`'s `address_prefix` to `10.0.6.0/24`.

### 2. The storage account's own firewall locks the VM out — resolved with the `Microsoft.Storage` service endpoint, not preserved

`README.md`'s documented scenario has the VM reach the storage account over its public endpoint (via the VS Code Azure Storage extension — see `README.md`'s "Current scenario" section and `infra/storage.py`'s original docstring). PR #9's `network_rule_set` has `default_action=DENY` and only lets through the IP `193.60.220.253` (a human on the Turing VPN, per `README-Storage.md` — not the VM) and traffic from `storage_subnet` (which nothing is deployed into; the VM lives in `vm_subnet`). The VM's own requests to the storage account's public endpoint match neither rule and are denied, regardless of which client makes them (VS Code's extension, `curl`, `az storage`, anything) — Azure Storage network rules are enforced ahead of authentication, so no amount of switching client tools on the VM side fixes this by itself.

**This plan resolves it by properly using the `Microsoft.Storage` service endpoint PR #9 already introduces for `storage_subnet`, extended to `vm_subnet`, rather than by adding an IP-based carve-out for the firewall's egress address.** Concretely: `vm_subnet` (defined in `infra/networking.py`) gets its own `Microsoft.Storage` service endpoint, and the storage account's `virtual_network_rules` gets a second entry for `vm_subnet.id` alongside the existing `storage_subnet` one. This is Microsoft's own documented fix for exactly this situation — a subnet behind a forced-tunnelling default route (`0.0.0.0/0` to an NVA, here the Application Firewall) that also needs to reach a network-restricted PaaS resource:

> "Configuring a default route (0.0.0.0/0) to force traffic through an on-premises firewall or network virtual appliance can break [...] connectivity. To resolve this, enable service endpoints on the [...] subnet for Azure SQL, Azure Storage [...]. This allows traffic to these services to use the Microsoft Azure backbone network, bypassing the forced tunnel. Ensure your firewall or virtual appliance does not block this traffic."
> — [Azure API Management networking guidance](https://learn.microsoft.com/en-us/azure/api-management/api-management-using-with-vnet), Microsoft Learn (the same forced-tunnel-plus-service-endpoint interaction, for a different Azure service facing the identical problem)

**The trade-off, made explicit rather than left implicit:** enabling the service endpoint on `vm_subnet` means the VM's storage traffic starts using a more specific system route than the `0.0.0.0/0` UDR, so it goes to the storage account directly over the Azure backbone instead of via the Application Firewall. That's a deliberate, accepted cost of this fix, not a bug:

- PR #7's `AllowAzureStorage` application rule (`infra/firewall.py`) stops seeing any real traffic once this ships — the firewall's FQDN-level allow/deny and its logging no longer apply to VM↔storage traffic. The rule is left in place (harmless, and still correct as *defence in depth* if the service endpoint were ever removed), matching the same "leave it, it's harmless" treatment `consolidating-firewall.md` already gives PR #7's NAT rule once Bastion coexists with it.
- **The VS Code Azure Storage extension workflow is not restored by this fix, and this plan does not attempt to restore it.** The storage-account-level ACL is now satisfied for the VM, but the extension's interactive sign-in and account-browsing also depend on Microsoft Entra ID and Azure Resource Manager control-plane endpoints (e.g. `login.microsoftonline.com`, `management.azure.com`) that were never added to the Application Firewall's allow-list — that gap predates this consolidation and is the same class of residual issue `consolidating-firewall.md` already flags for the VS Code Marketplace endpoints (not pinned down, not guessed at, left for the user to confirm against a live deployment). Widening the firewall's FQDN allow-list to chase that gap is out of scope here; it would belong in a future pass over `consolidating-firewall.md` if the interactive extension workflow is ever wanted back. Per the user's direction, this is accepted as-is, and the VM gets a different, working access path instead (below).

### The VM's replacement access path: Azure CLI, not REST or the extension

With the fix above, the VM can still reach the storage account's **data plane** (`*.blob.core.windows.net`) directly — it's the extension's separate control-plane/sign-in dependency that's given up, not blob access itself. Of the alternatives, Azure CLI is the most convenient fit for this repository specifically:

- `CLAUDE.md`'s tech stack already commits to **Azure CLI (`az login`) as the only supported authentication method** — the VM already needs a working `az` session for everything else in this repo's documented workflow, so `az storage blob upload`/`download --auth-mode login` reuses credentials and tooling that are already there, rather than introducing a new one.
- It needs no SAS token issuance/rotation (unlike the Storage Explorer workflow `README-Storage.md` already documents for the Turing-VPN human path) — just an Entra ID role assignment, the same `Storage Blob Data Contributor` role `README.md` already asks users to grant themselves for the Pulumi-state container, so it's a familiar pattern rather than a new concept.
- It needs no manual request-signing the way a raw REST API call would (`Authorization` header construction, SAS/key handling) — `az storage blob upload/download --auth-mode login` handles that internally against the already-signed-in account.

`README-Storage.md` (see step 6 below) documents this concretely:

```sh
STORAGE_ACCOUNT=$(pulumi stack output storage_account_name)

# Upload a file to the demo container
az storage blob upload \
  --account-name "$STORAGE_ACCOUNT" --container-name "rse-demo-container" \
  --name <blob-name> --file <local-path> --auth-mode login

# Download a file from the demo container
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" --container-name "rse-demo-container" \
  --name <blob-name> --file <local-path> --auth-mode login
```

The signed-in identity needs the **Storage Blob Data Contributor** (or **Storage Blob Data Reader**, for download-only access) role on the storage account or its resource group — assigned the same way `README.md` already documents for the Pulumi-state container:

```sh
az role assignment create --role "Storage Blob Data Contributor" --assignee <email> \
  --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Storage/storageAccounts/<storage-account>
```

## Steps

1. **Merge, don't rebase.** From `consolidation`:
   ```sh
   git merge origin/05-storage
   ```
   Expect this to complete with **no conflicts** — confirm with `git status` afterwards. (If a future rebase of `05-storage` changes this, treat any conflict the same way the other three consolidations' `infra/__init__.py`/`__main__.py` conflicts were resolved: keep both sides.)

2. **Fix the subnet address collision** (see problem 1 above). In `infra/storage.py`, change:
   ```python
   storage_subnet = network.Subnet(
       "rse-storage-subnet",
       resource_group_name=resource_group.name,
       virtual_network_name=virtual_network.name,
       address_prefix="10.0.6.0/24",
       ...
   ```
   (only the `address_prefix` value changes, from `10.0.5.0/24` to `10.0.6.0/24`).

3. **Give `vm_subnet` its own `Microsoft.Storage` service endpoint** (see problem 2 above). In `infra/networking.py`, add `service_endpoints` to the existing `vm_subnet` definition:
   ```python
   vm_subnet = network.Subnet(
       "rse-vm-subnet",
       resource_group_name=resource_group.name,
       virtual_network_name=virtual_network.name,
       address_prefix="10.0.1.0/24",
       network_security_group=network.NetworkSecurityGroupArgs(
           id=network_security_group.id
       ),
       route_table=network.RouteTableArgs(id=route_table.id),
       service_endpoints=[
           network.ServiceEndpointPropertiesFormatArgs(
               service="Microsoft.Storage",
           )
       ],
   )
   ```

4. **Add `vm_subnet` to the storage account's `virtual_network_rules`.** In `infra/storage.py`, import `vm_subnet` alongside the module's existing `infra.networking` import and extend the `network_rule_set`:
   ```python
   from infra.networking import network_security_group, virtual_network, vm_subnet
   ```
   ```python
   network_rule_set = (
       storage.NetworkRuleSetArgs(
           bypass=storage.Bypass.AZURE_SERVICES,
           default_action=storage.DefaultAction.DENY,
           ip_rules=ip_rules,
           virtual_network_rules=[
               storage.VirtualNetworkRuleArgs(
                   virtual_network_resource_id=storage_subnet.id,
               ),
               storage.VirtualNetworkRuleArgs(
                   virtual_network_resource_id=vm_subnet.id,
               ),
           ],
       ),
   )
   ```
   `ip_rules` (the Turing VPN entry) is left exactly as PR #9 wrote it — no firewall-egress-IP addition is needed with this approach.

5. **Re-export the new resources from `infra/__init__.py`**, following the package's existing "re-export every resource" convention (matching how PR #7's consolidation added `firewall`/`firewall_public_ip`):
   ```python
   from infra.storage import (
       blob_container,
       storage_account,
       storage_account_private_endpoint,
       storage_subnet,
   )
   ```
   and in `__all__` (alphabetical, matching the file's existing ordering):
   ```text
   "storage_account",
   "storage_account_private_endpoint",
   "storage_subnet",
   ```
   No changes are needed to `__main__.py` — PR #9 adds no new stack outputs and none of the existing ones need updating.

6. **Close the test coverage gap.** PR #9 adds zero tests for any of `infra/storage.py`'s new resources, and this plan adds a service endpoint to `vm_subnet` that also needs covering. Extend `tests/test_storage.py` and `tests/test_networking.py`, mirroring this repo's existing style (in particular `tests/test_firewall.py` and `tests/test_monitoring.py`'s private-endpoint tests, for the nested-Args-as-dict mocking quirk and the private-endpoint pattern respectively). As with the previous three consolidations, this must be written and run against the merged-plus-fixed code in a disposable worktree before being treated as done.

   `tests/test_storage.py`'s updated import line:
   ```python
   from infra.firewall import firewall_management_subnet
   from infra.networking import vm_subnet
   from infra.storage import (
       blob_container,
       storage_account,
       storage_account_private_endpoint,
       storage_subnet,
   )
   ```

   New tests to add to `tests/test_storage.py`:
   ```python
   @pulumi.runtime.test
   def test_storage_subnet_urn(self):
       def check_urn(urn: str) -> None:
           self.assertIn("rse-storage-subnet", urn)

       return storage_subnet.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]


   @pulumi.runtime.test
   def test_storage_subnet_has_the_microsoft_storage_service_endpoint(self):
       def check(service_endpoints: list) -> None:
           self.assertEqual(len(service_endpoints), 1)
           self.assertEqual(service_endpoints[0]["service"], "Microsoft.Storage")

       return storage_subnet.service_endpoints.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )


   @pulumi.runtime.test
   def test_storage_subnet_does_not_overlap_the_firewall_management_subnet(self):
       def check(args: tuple) -> None:
           storage_prefix, firewall_management_prefix = args
           self.assertNotEqual(storage_prefix, firewall_management_prefix)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           storage_subnet.address_prefix, firewall_management_subnet.address_prefix
       ).apply(check)  # ty: ignore[invalid-argument-type]


   @pulumi.runtime.test
   def test_storage_account_denies_by_default_with_azure_services_bypass(self):
       def check(network_rule_set) -> None:
           self.assertEqual(network_rule_set["default_action"], "Deny")
           self.assertEqual(network_rule_set["bypass"], "AzureServices")

       return storage_account.network_rule_set.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )


   @pulumi.runtime.test
   def test_storage_account_ip_rules_allow_only_the_turing_vpn(self):
       def check(network_rule_set) -> None:
           addresses = {
               rule["i_p_address_or_range"] for rule in network_rule_set["ip_rules"]
           }
           self.assertEqual(addresses, {"193.60.220.253"})

       return storage_account.network_rule_set.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )


   @pulumi.runtime.test
   def test_storage_account_virtual_network_rules_include_storage_subnet_and_vm_subnet(
       self,
   ):
       def check(args: tuple) -> None:
           network_rule_set, storage_subnet_id, vm_subnet_id = args
           vnet_rule_ids = {
               rule["virtual_network_resource_id"]
               for rule in network_rule_set["virtual_network_rules"]
           }
           self.assertIn(storage_subnet_id, vnet_rule_ids)
           self.assertIn(vm_subnet_id, vnet_rule_ids)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           storage_account.network_rule_set, storage_subnet.id, vm_subnet.id
       ).apply(check)  # ty: ignore[invalid-argument-type]


   @pulumi.runtime.test
   def test_storage_account_encrypts_blob_and_file_at_rest(self):
       def check(encryption) -> None:
           services = encryption["services"]
           self.assertTrue(services["blob"]["enabled"])
           self.assertTrue(services["file"]["enabled"])

       return storage_account.encryption.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )


   @pulumi.runtime.test
   def test_storage_account_private_endpoint_targets_blob(self):
       def check(connections: list) -> None:
           self.assertEqual(len(connections), 1)
           self.assertEqual(connections[0].group_ids, ["blob"])

       return storage_account_private_endpoint.private_link_service_connections.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )


   @pulumi.runtime.test
   def test_storage_account_private_endpoint_uses_the_storage_subnet(self):
       def check(args: tuple) -> None:
           endpoint_subnet_id, subnet_id = args
           self.assertEqual(endpoint_subnet_id, subnet_id)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           storage_account_private_endpoint.subnet.id, storage_subnet.id
       ).apply(check)  # ty: ignore[invalid-argument-type]
   ```

   New test to add to `tests/test_networking.py` (new import plus one new test method):
   ```python
   @pulumi.runtime.test
   def test_vm_subnet_has_the_microsoft_storage_service_endpoint(self):
       def check(service_endpoints: list) -> None:
           self.assertEqual(len(service_endpoints), 1)
           self.assertEqual(service_endpoints[0]["service"], "Microsoft.Storage")

       return vm_subnet.service_endpoints.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )
   ```

   This must be confirmed passing (9 new tests in `test_storage.py`, 1 in `test_networking.py`) alongside the existing 60, in a disposable worktree, before being marked done here.

7. **Update `README.md`'s "Project structure" section, `README-Storage.md`, and `README-Firewall.md`** to reflect the fixes and the access-path change:
   - Update the `storage.py` bullet in `README.md`:
     ```markdown
     - `storage.py` — the storage account and its blob container, restricted by a Storage Account firewall to the Turing VPN and, via a `Microsoft.Storage` service endpoint, the VM's own subnet (see `README-Storage.md` — this is why the VM uses `az storage` rather than the VS Code Azure Storage extension), plus at-rest encryption and a (currently unused) private endpoint for the blob service
     ```
   - Update `README.md`'s "Current scenario" section (or wherever it currently says the VM reaches the storage account via the VS Code extension) to say the VM now reaches the storage account via Azure CLI (`az storage blob upload`/`download --auth-mode login`), per `README-Storage.md`.
   - In `README-Storage.md`:
     - In the subnet section, fix the address range (`10.0.5.0/24` → `10.0.6.0/24`) and note briefly why (`10.0.5.0/24` is already the firewall's management subnet).
     - Add a new section explaining that `vm_subnet` also gets the `Microsoft.Storage` service endpoint and a matching `virtual_network_rules` entry, why (the VM's own traffic needs a path in, and this is Microsoft's documented fix for a forced-tunnelled subnet needing PaaS access — cite the reasoning in "The compatibility problems" above), and the resulting trade-off (this traffic bypasses the Application Firewall, and the VS Code Azure Storage extension's separate sign-in/control-plane dependency is not restored by this fix).
     - Replace/extend the "Creating a Blob Storage SAS URL" section with the `az storage blob upload`/`download --auth-mode login` workflow above, framed as the VM's own access path (the SAS/Storage Explorer workflow remains valid for the Turing-VPN human path, unchanged).
   - In `README-Firewall.md`, add a short note next to `AllowAzureStorage` that this rule is no longer exercised by real VM traffic once `05-storage` lands, since that traffic now bypasses the firewall via `vm_subnet`'s service endpoint — left in place as harmless defence-in-depth, same treatment as the NAT-rule/Bastion coexistence note already there.

8. **Manual verification that the merge itself is correct.**
   ```sh
   git log --oneline -5                          # merge commit + "Add Azure Storage firewall rules" both present
   git status                                     # working tree clean, no leftover conflict markers
   grep -rn "^<<<<<<<\|^=======\|^>>>>>>>" --include='*.py' .   # no unresolved conflict markers
   git diff origin/05-storage consolidation -- infra/storage.py infra/networking.py README-Storage.md
                                                   # should show only the step 2-4 fixes and the step-7 doc updates
   ```

9. **Manual verification that the Pulumi program actually implements this end-to-end.** Per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature), `pulumi preview`/`pulumi up` are **run by the user, not Claude** — unit tests and static checks are as far as automated verification goes here, and neither can confirm real Azure routing/network-ACL behaviour (that depends on live Azure networking, which the mocked test suite doesn't touch).
   - `pulumi preview` first — new resources only (`storage_subnet`, the private endpoint), plus in-place updates to `vm_subnet` and `storage_account`; read the diff and confirm nothing existing is being replaced.
   - `pulumi up`, then confirm in the Azure Portal (or `az storage account show --name <name> --query networkRuleSet`) that `defaultAction` is `Deny` and both `virtualNetworkRules` entries (`storage_subnet` and `vm_subnet`) are present, and that `vm_subnet`'s effective route table still sends `0.0.0.0/0` to the firewall (per `consolidating-firewall.md`) even though storage traffic bypasses it.
   - **Confirm `az storage blob upload`/`download --auth-mode login` works from the VM**, after assigning the signed-in identity `Storage Blob Data Contributor` per the snippet above — this is the workflow this plan's fix is specifically for.
   - **Confirm the VS Code Azure Storage extension does *not* work from the VM**, and that this is because of its sign-in/control-plane dependency rather than the storage account's own network ACL (e.g. check whether the failure is a sign-in/redirect failure rather than an "IP not authorized" storage error) — this distinction is what "The compatibility problems" above claims, and it's worth confirming rather than assuming.
   - Confirm the Turing-VPN-only access path in `README-Storage.md` (generating a SAS URL and connecting via Storage Explorer, from a device on the Turing VPN) still works, unchanged.
   - Optionally, confirm access is actually denied from an unauthorised IP (e.g. attempt the same SAS URL from a device not on the Turing VPN, and not on `vm_subnet`).

## Verification checklist

- [ ] `git merge origin/05-storage` completes with no conflicts.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes, including the 9 new tests added to `tests/test_storage.py` and the 1 new test added to `tests/test_networking.py` (70 tests total).
- [ ] `infra/storage.py`'s `storage_subnet` uses `10.0.6.0/24`, not the `firewall_management_subnet`-colliding `10.0.5.0/24`.
- [ ] `infra/networking.py`'s `vm_subnet` has a `Microsoft.Storage` service endpoint.
- [ ] `infra/storage.py`'s `network_rule_set.virtual_network_rules` includes both `storage_subnet` and `vm_subnet`; `ip_rules` still allows only `193.60.220.253`.
- [ ] `infra/__init__.py` re-exports `storage_subnet` and `storage_account_private_endpoint` alongside the existing `storage_account`/`blob_container`.
- [ ] `README.md`'s project structure/"Current scenario" sections, `README-Storage.md`, and `README-Firewall.md` reflect the corrected subnet range, the `vm_subnet` service endpoint and its trade-off, and the `az storage blob` access path replacing the VS Code extension.
- [ ] (Manual, by the user) `git log`/`git status`/the targeted `git diff` in step 8 confirm the merge captured every file PR #9 touches, with no leftover conflict markers and no unintended drift beyond this plan's fixes.
- [ ] (Manual, by the user) `pulumi preview`/`pulumi up` succeed against the `dev` stack; the storage account's network rule set and `vm_subnet`'s service endpoint match what's designed here.
- [ ] (Manual, by the user) `az storage blob upload`/`download --auth-mode login` works from the VM with the `Storage Blob Data Contributor` role assigned.
- [ ] (Manual, by the user) The VS Code Azure Storage extension does not work from the VM, and the Turing-VPN SAS-URL workflow in `README-Storage.md` still does.
- [ ] (Manual, by the user) Access from an unauthorised IP/subnet is actually denied.

## Out of scope for this document

- PR #8 (managed identity) — this plan only covers bringing PR #9 into `consolidation`, on top of the Bastion, Log Analytics, and Application Firewall work already there. A later consolidation pass for PR #8 gets its own plan document.
- Widening the Application Firewall's FQDN allow-list (`infra/firewall.py`) to restore the VS Code Azure Storage extension's Entra ID/Azure Resource Manager control-plane dependencies. Per the user's direction, that workflow is intentionally not preserved in this consolidation; if it's ever wanted back, it belongs in a future pass over `consolidating-firewall.md`, alongside its already-flagged VS Code Marketplace gap.
- Wiring up `storage_account_private_endpoint` with an actual private DNS zone (mirroring `infra/dns.py`'s pattern for the monitoring private endpoint) so it's actually reachable over private link — PR #9 doesn't do this either, and it isn't needed for the `az storage blob` workflow above (which goes over the service-endpoint-backed public data-plane path, not private link). Flagged here as a natural next step for a genuinely "private" storage account, not attempted in this consolidation.
- Removing the now-unexercised `AllowAzureStorage` application rule from `infra/firewall.py`. Left in place as harmless defence-in-depth (see step 7); removing it is a cleanup call for the user, not a consolidation blocker.
- Revisiting whether `storage_subnet` should reuse the VM's `network_security_group` (as PR #9 does) rather than defining its own — harmless as-is (the NSG's only rules are inbound-SSH/RDP allows that don't apply to anything in `storage_subnet`), but a design question for the user, not a consolidation blocker.
- Claude running `pulumi preview`/`pulumi up` itself — per [CLAUDE.md](../CLAUDE.md), that's the user's to run manually (step 9 above is written for the user to execute, not for Claude to automate).
