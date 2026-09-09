# Consolidating Storage Firewall — PR #9

Plan to bring [PR #9 "Add Azure Storage firewall rules"](https://github.com/alan-turing-institute/rse-cloud-cybersecurity/pull/9) (branch `05-storage`) into `consolidation`, so the resulting branch still passes the project's verification gate (`ruff check`, `ruff format --check`, `ty check`, `pytest` — see [`CLAUDE.md`](../CLAUDE.md)), without breaking the Bastion, Log Analytics, and Application Firewall work already on `consolidation` ([`consolidating-bastion.md`](consolidating-bastion.md), [`consolidating-logs.md`](consolidating-logs.md), [`consolidating-firewall.md`](consolidating-firewall.md)).

**The textual merge itself is clean** — unlike the previous three consolidations, `git merge-tree` reports no conflicts at all: PR #9 only touches `infra/storage.py` (untouched by every other branch already on `consolidation`) and adds a new `README-Storage.md`. But a clean textual merge is not the same as a working one. Checked directly against what's already on `consolidation`, PR #9's storage subnet collides with an existing subnet's address range (a guaranteed `pulumi up` failure, not a silent one), and its storage-account network ACL would silently lock the VM itself out of the storage account it's meant to use — see "The compatibility problems" below before anything else.

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

### 2. The storage account's own firewall would lock the VM out (silent break)

`README.md`'s documented scenario has the VM reach the storage account over its public endpoint (via the VS Code Azure Storage extension — see `README.md`'s "Current scenario" section and `infra/storage.py`'s original docstring). PR #7's Application Firewall consolidation (already on `consolidation`) already anticipated this: it added an `AllowAzureStorage` application rule (`infra/firewall.py`) specifically so the VM's outbound HTTPS to `*.blob.core.windows.net` is allowed through the firewall, because **all** of the VM's outbound traffic is forced through it via the `0.0.0.0/0` route (`infra/networking.py`'s `route_table` + `infra/firewall.py`'s `route`) and SNATted to `firewall_public_ip`.

PR #9's `network_rule_set` sits *behind* that firewall rule, at the storage account itself, with `default_action=DENY` and only two things let through: the IP `193.60.220.253` (a human on the Turing VPN, per `README-Storage.md` — not the VM) and traffic from `storage_subnet` (which nothing is actually deployed into; the VM lives in `vm_subnet`). The VM's requests reach the storage account's public endpoint SNATted to `firewall_public_ip` — an address that is neither of those two things. Azure Firewall letting the traffic *out* doesn't help if the storage account then denies it on arrival: the documented VS Code Azure Storage extension workflow would break, and nothing in `ruff`/`ty`/`pytest` catches it, because the mocked test suite never exercises real network ACLs.

**A tempting-looking wrong fix, called out explicitly so it isn't tried:** adding a `Microsoft.Storage` service endpoint to `vm_subnet` (so the VM's storage traffic gets its own VNet-rule entry) looks like the obvious parallel to `storage_subnet`'s own service endpoint. It would actually make things worse: enabling a service endpoint on a subnet makes Azure insert more-specific system routes for that service's address ranges, and — per the same "more specific route wins over a UDR" reasoning `consolidating-firewall.md` already relied on for VNet-local traffic — that would silently pull the VM's storage traffic *off* the `0.0.0.0/0` route and around the firewall entirely. That's a documented Azure gotcha (service endpoints + NVA-forced egress), and it would undermine the whole point of PR #7's centralised-egress design, not just fail to fix this problem.

**Fix applied in this plan:** keep all VM egress going through the firewall (as PR #7 already designed for) and instead extend the storage account's own `ip_rules` with `firewall_public_ip.ip_address` — the address the VM's storage traffic actually arrives from — alongside the existing Turing-VPN entry. `bypass=AZURE_SERVICES` and the `storage_subnet` VNet rule are both left as PR #9 wrote them; they're for a different access pattern (trusted first-party Azure services, and a currently-unused subnet respectively) and don't need touching to fix this.

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

3. **Fix the storage account's IP allow-list so the VM can still reach it** (see problem 2 above). In `infra/storage.py`, import `firewall_public_ip` and extend `ip_rules`:
   ```python
   from infra.firewall import firewall_public_ip
   from infra.networking import network_security_group, virtual_network
   ```
   ```python
   # List the IP addresses or ranges permitted access:
   # - 193.60.220.253 is the Turing VPN's public egress address, for direct
   #   human access (e.g. Storage Explorer, per README-Storage.md).
   # - firewall_public_ip is where the VM's own storage traffic arrives from,
   #   since all VM egress is routed through the Application Firewall (see
   #   consolidating-firewall.md) rather than leaving from vm_subnet directly.
   ip_rules = [
       storage.IPRuleArgs(
           action=storage.Action.ALLOW,
           i_p_address_or_range="193.60.220.253",
       ),
       storage.IPRuleArgs(
           action=storage.Action.ALLOW,
           i_p_address_or_range=firewall_public_ip.ip_address,
       ),
   ]
   ```
   No change is needed to `application_rule_collections` in `infra/firewall.py` — PR #7's `AllowAzureStorage` rule already covers this traffic on the firewall side; this step just makes the storage account's own ACL agree with it.

4. **Re-export the new resources from `infra/__init__.py`**, following the package's existing "re-export every resource" convention (matching how PR #7's consolidation added `firewall`/`firewall_public_ip`):
   ```python
   from infra.storage import blob_container, storage_account, storage_subnet
   ```
   and in `__all__` (alphabetical, matching the file's existing ordering):
   ```text
   "storage_account",
   "storage_subnet",
   ```
   `storage_account_private_endpoint` is left un-re-exported, consistent with how `infra/monitoring.py`'s own `log_analytics_private_endpoint` **is** re-exported today — actually, for consistency with that existing precedent, also add:
   ```python
   from infra.storage import (
       blob_container,
       storage_account,
       storage_account_private_endpoint,
       storage_subnet,
   )
   ```
   and `"storage_account_private_endpoint"` to `__all__`. No changes are needed to `__main__.py` — PR #9 adds no new stack outputs and none of the existing ones need updating.

5. **Close the test coverage gap.** PR #9 adds zero tests for any of `infra/storage.py`'s new resources. Extend `tests/test_storage.py`, mirroring this repo's existing style (in particular `tests/test_firewall.py` and `tests/test_monitoring.py`'s private-endpoint tests, for the nested-Args-as-dict mocking quirk and the private-endpoint pattern respectively). As with the previous three consolidations, this must be written and run against the merged-plus-fixed code in a disposable worktree before being treated as done.

   Updated import line:
   ```python
   from infra.firewall import firewall_public_ip
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
   def test_storage_account_allows_the_turing_vpn_and_the_firewalls_egress_ip(self):
       def check(args: tuple) -> None:
           network_rule_set, firewall_ip = args
           addresses = {
               rule["i_p_address_or_range"] for rule in network_rule_set["ip_rules"]
           }
           self.assertIn("193.60.220.253", addresses)
           self.assertIn(firewall_ip, addresses)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           storage_account.network_rule_set, firewall_public_ip.ip_address
       ).apply(check)  # ty: ignore[invalid-argument-type]

   @pulumi.runtime.test
   def test_storage_account_virtual_network_rule_targets_the_storage_subnet(self):
       def check(args: tuple) -> None:
           network_rule_set, subnet_id = args
           vnet_rule_ids = {
               rule["virtual_network_resource_id"]
               for rule in network_rule_set["virtual_network_rules"]
           }
           self.assertIn(subnet_id, vnet_rule_ids)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           storage_account.network_rule_set, storage_subnet.id
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
   `firewall_management_subnet` also needs importing in the test file:
   ```python
   from infra.firewall import firewall_management_subnet, firewall_public_ip
   ```

   This must be confirmed passing (9 new tests) alongside the existing 60, in a disposable worktree, before being marked done here.

6. **Update `README.md`'s "Project structure" section and `README-Storage.md`** to reflect the two fixes:
   - Update the `storage.py` bullet:
     ```markdown
     - `storage.py` — the storage account and its blob container, restricted by a Storage Account firewall to the Turing VPN and the VM's own egress path through the Application Firewall (see `README-Storage.md`), plus at-rest encryption and a (currently unused) private endpoint for the blob service
     ```
   - In `README-Storage.md`, in the "Pass IP rules during creation" section, add a paragraph explaining the second `ip_rules` entry: the VM itself doesn't connect from the Turing VPN's address, it connects from wherever the Application Firewall's outbound IP is (per `README-Firewall.md`), since all of the VM's egress is routed through the firewall — so that address needs allowing too, or the VM's own storage access (the VS Code extension workflow in `README.md`) breaks.
   - In `README-Storage.md`'s subnet section, fix the address range mentioned (`10.0.5.0/24` → `10.0.6.0/24`) if the PR's text calls out the literal value, and note briefly why (`10.0.5.0/24` is already the firewall's management subnet).

7. **Manual verification that the merge itself is correct.**
   ```sh
   git log --oneline -5                          # merge commit + "Add Azure Storage firewall rules" both present
   git status                                     # working tree clean, no leftover conflict markers
   grep -rn "^<<<<<<<\|^=======\|^>>>>>>>" --include='*.py' .   # no unresolved conflict markers
   git diff origin/05-storage consolidation -- infra/storage.py README-Storage.md
                                                   # should show only the step-2/3 fixes and the step-6 doc updates
   ```

8. **Manual verification that the Pulumi program actually implements this end-to-end.** Per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature), `pulumi preview`/`pulumi up` are **run by the user, not Claude** — unit tests and static checks are as far as automated verification goes here, and neither can confirm real Storage Account network ACL behaviour (that depends on live Azure networking, which the mocked test suite doesn't touch).
   - `pulumi preview` first — new resources only (`storage_subnet`, the private endpoint), plus an in-place update to `storage_account`; read the diff and confirm nothing existing is being replaced.
   - `pulumi up`, then confirm in the Azure Portal (or `az storage account show --name <name> --query networkRuleSet`) that `defaultAction` is `Deny` and both IP rules (the Turing VPN address and the firewall's actual public IP) are present.
   - **Confirm the documented VS Code Azure Storage extension workflow (`README.md`) still works from the VM** — this is the one this plan's fix is specifically for. If it still fails, check what source IP the storage account's diagnostic logs (or a plain deny) show and compare against `pulumi stack output firewall_public_ip`.
   - Confirm the Turing-VPN-only access path in `README-Storage.md` (generating a SAS URL and connecting via Storage Explorer, from a device on the Turing VPN) still works.
   - Optionally, confirm access is actually denied from an unauthorised IP (e.g. attempt the same SAS URL from a device not on the Turing VPN or the firewall).

## Verification checklist

- [ ] `git merge origin/05-storage` completes with no conflicts.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes, including the 9 new tests added to `tests/test_storage.py` (69 tests total).
- [ ] `infra/storage.py`'s `storage_subnet` uses `10.0.6.0/24`, not the `firewall_management_subnet`-colliding `10.0.5.0/24`.
- [ ] `infra/storage.py`'s `ip_rules` allows both `193.60.220.253` and `firewall_public_ip.ip_address`.
- [ ] `infra/__init__.py` re-exports `storage_subnet` and `storage_account_private_endpoint` alongside the existing `storage_account`/`blob_container`.
- [ ] `README.md`'s project structure section and `README-Storage.md` reflect both fixes (the corrected subnet range and why the firewall's egress IP needs allowing).
- [ ] (Manual, by the user) `git log`/`git status`/the targeted `git diff` in step 7 confirm the merge captured every file PR #9 touches, with no leftover conflict markers and no unintended drift beyond this plan's fixes.
- [ ] (Manual, by the user) `pulumi preview`/`pulumi up` succeed against the `dev` stack; the storage account's network rule set matches what's designed here.
- [ ] (Manual, by the user) The documented VS Code Azure Storage extension workflow still works from the VM, and the Turing-VPN SAS-URL workflow in `README-Storage.md` still works.
- [ ] (Manual, by the user) Access from an unauthorised IP is actually denied.

## Out of scope for this document

- PR #8 (managed identity) — this plan only covers bringing PR #9 into `consolidation`, on top of the Bastion, Log Analytics, and Application Firewall work already there. A later consolidation pass for PR #8 gets its own plan document.
- Wiring up `storage_account_private_endpoint` with an actual private DNS zone (mirroring `infra/dns.py`'s pattern for the monitoring private endpoint) so it's actually reachable over private link — PR #9 doesn't do this either, and adding it isn't necessary to make the existing public-endpoint workflow keep working. Flagged here as a natural next step for a genuinely "private" storage account, not attempted in this consolidation.
- Reconciling `storage_subnet`'s `virtual_network_rules` entry with the fact that nothing is actually deployed into `storage_subnet` (it exists solely to satisfy the service-endpoint requirement for IP-based rules) — left as PR #9 wrote it, since removing it isn't necessary to fix either compatibility problem above.
- Revisiting whether `storage_subnet` should reuse the VM's `network_security_group` (as PR #9 does) rather than defining its own — harmless as-is (the NSG's only rules are inbound-SSH/RDP allows that don't apply to anything in `storage_subnet`), but a design question for the user, not a consolidation blocker.
- Claude running `pulumi preview`/`pulumi up` itself — per [CLAUDE.md](../CLAUDE.md), that's the user's to run manually (step 8 above is written for the user to execute, not for Claude to automate).
