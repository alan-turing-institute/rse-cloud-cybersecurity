# Consolidating Firewall — PR #7

Plan to bring [PR #7 "Add Application Firewall to VM"](https://github.com/alan-turing-institute/rse-cloud-cybersecurity/pull/7) (branch `04-firewall`) into `consolidation`, so the resulting branch still passes the project's verification gate (`ruff check`, `ruff format --check`, `ty check`, `pytest` — see [`CLAUDE.md`](../CLAUDE.md)), without breaking the Bastion and Log Analytics work already on `consolidation` ([`consolidating-bastion.md`](consolidating-bastion.md), [`consolidating-logs.md`](consolidating-logs.md)).

**This one is different from the previous two consolidations.** PR #7's firewall rules were written for a different reference scenario and don't match what this repository's own VM actually needs. Merged as-is, the Pulumi program would build, `ruff`/`ty`/`pytest` would all pass, and `pulumi up` would likely succeed — but the VM's cloud-init provisioning and its documented SQL/Storage connectivity would silently break the moment the firewall's route table takes effect, because none of that traffic is on PR #7's allow-list. See "The compatibility problem" below before anything else.

## Starting point

- `consolidation`'s current tip (`ca47479`) has PR #3 (Bastion) and PR #5 (Log Analytics) folded in.
- `04-firewall` (`e28f74a`) branches from `98b979f` — a commit that predates *both* the Bastion and Log Analytics work on `consolidation`. Like the Log Analytics merge, this **will not be a fast-forward**.
- A dry-run merge (`git merge-tree`, then a full merge attempt in a disposable `git worktree`) confirms three textual conflicts: `__main__.py`, `infra/__init__.py` (both for the same reason as the Log Analytics merge — parallel export additions), and none in `infra/networking.py`, which auto-merges cleanly even though both this PR and the Bastion/Log Analytics work touch it.
- The full merge (conflicts resolved, plus the fix described below) was verified end-to-end in a disposable worktree: `ruff check`, `ruff format --check`, `ty check`, and `pytest` all pass, with 60 tests total (up from 52).

## What PR #7 changes

- Adds `infra/firewall.py`: two new subnets (`AzureFirewallSubnet`, `AzureFirewallManagementSubnet` — exact names Azure requires), two Standard/static public IPs (firewall + firewall management, the latter mandatory for the Basic SKU), a NAT rule collection forwarding SSH from the firewall's public IP to the VM's private IP (restricted to source IP `193.60.220.253`), an application rule collection allowing three specific outbound FQDNs (`keyserver.ubuntu.com`, `api.snapcraft.io`, `download1.rstudio.org`) plus a deny collection for three Snapcraft upload/login FQDNs, the `AzureFirewall` resource itself (Basic SKU), and a `Route` sending `0.0.0.0/0` through the firewall.
- Updates `infra/networking.py`: adds a `RouteTable` (`route_table`, routes ignored post-creation so the `Route` above can attach independently) and attaches it to `vm_subnet`.
- Updates `infra/__init__.py`: re-exports `firewall`, `firewall_public_ip`.
- Updates `__main__.py`: imports `public_ip` (the VM's own public IP, from before Bastion removed it — stale on this branch) and exports `vm_public_ip`/`firewall_public_ip`.
- Adds `README-Firewall.md`: a standalone write-up (mirrors `README-Bastion.md`/`README-LogAnalytics.md`'s style).
- Adds **no tests** for any of this — `tests/`, `conftest.py`, and `pyproject.toml`/`uv.lock` are untouched by PR #7.

## The compatibility problem

Attaching `route_table` to `vm_subnet` means **every** outbound connection from the VM (except VNet-local traffic, which Azure's more-specific system routes keep off the `0.0.0.0/0` route regardless of the UDR) now goes through the firewall, where PR #7's application rules allow exactly three FQDNs and deny three more — everything else is an implicit deny. Checked directly against what this VM actually does:

- `infra/templates/vm-cloud-init.yaml.j2` runs `apt-get update`/`apt-get install` against Ubuntu's default archive mirrors, then adds and installs from the VS Code apt repo (`packages.microsoft.com`) and the Google Chrome apt repo (`dl.google.com`). None of `keyserver.ubuntu.com`, `api.snapcraft.io`, or `download1.rstudio.org` cover any of this — PR #7's rules were written for a different (snap/RStudio-based) reference scenario, not this repo's actual apt/VS Code/Chrome-based provisioning.
- `infra/database.py`'s `sql_firewall_rule` ("rse-sql-allow-all") and `infra/storage.py`'s docstring ("reachable over the public internet at this stage") confirm both the SQL Database and the Storage Account are reached over their **public** endpoints, not a private link — this is exactly how `README.md`'s documented VS Code `mssql`/Azure Storage extension workflow reaches them. Neither `*.database.windows.net` nor `*.blob.core.windows.net` is on PR #7's allow-list either.
- None of this is caught by `ruff`/`ty`/`pytest` — the mocked test suite never exercises real network egress, so the merge would look completely clean right up until someone actually deploys and watches cloud-init fail or the VS Code extensions fail to reach the database/storage account.

**Fix applied in this plan:** extend the existing `workspaces-allow-restricted` application rule collection in `infra/firewall.py` with five more rules covering what this VM's cloud-init and documented workflows actually need (Ubuntu archives, the VS Code and Chrome apt repos, and the SQL/Storage public endpoints — the last one using Azure Firewall's `MSSQL` application-rule protocol type). This was checked directly against `infra/templates/vm-cloud-init.yaml.j2` and the actual public-endpoint setup in `infra/database.py`/`infra/storage.py`, not guessed. One residual gap is flagged rather than guessed at: the VS Code Marketplace endpoints the `code --install-extension` steps also need (e.g. `marketplace.visualstudio.com`, `*.gallerycdn.vsassets.io`) aren't pinned down here, since that CDN's endpoint set isn't officially documented as a fixed list and this can't be verified without an actual deployment (which, per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature), is the user's to run, not Claude's) — this is called out explicitly in `README-Firewall.md` and in the manual-verification step below, not silently left broken.

**A second, smaller design note (not a bug):** PR #7's NAT rule adds a second way to reach the VM directly — SSH forwarded from the firewall's own public IP to the VM, for one hard-coded source IP. This coexists with Bastion (PR #3) rather than replacing it, since they front different public IPs and the VM still has none of its own. Kept as-is (it's a legitimate demo of an alternative, narrower-scope access pattern), but `README-Firewall.md` is updated to say so explicitly, since its original wording ("connecting to the virtual machine must be done using the firewall's public IP") reads as if it were the *only* way in, which is no longer true once Bastion is already on `consolidation`.

## Steps

1. **Merge, don't rebase.** From `consolidation`:
   ```sh
   git merge origin/04-firewall
   ```
   Expect it to stop with conflicts in `__main__.py` and `infra/__init__.py` — resolve them, don't abort. `infra/networking.py` auto-merges without a conflict.

2. **Resolve the `__main__.py` conflict.** PR #7's own version imports `public_ip` only to export a `vm_public_ip` stack output — both stale, since Bastion already removed the VM's public IP (`vm_public_ip` is intentionally not a stack output any more, per `consolidating-bastion.md`'s checklist). Drop that import and export entirely; keep the Bastion exports and add `firewall_public_ip`:
   ```python
   from infra import (
       bastion_host,
       bastion_public_ip,
       db_admin_password,
       firewall_public_ip,
       resource_group,
       sql_server,
       storage_account,
       virtual_machine,
       vm_admin_password,
   )
   ```
   ```python
   pulumi.export("bastion_name", bastion_host.name)
   pulumi.export("bastion_id", bastion_host.id)
   pulumi.export("bastion_public_ip", bastion_public_ip.ip_address)
   pulumi.export("firewall_public_ip", firewall_public_ip.ip_address)
   ```

3. **Resolve the `infra/__init__.py` conflict** by keeping both sides, alphabetically ordered (matching the file's existing convention — same pattern as the Log Analytics consolidation):
   ```python
   from infra.dns import monitoring_dns_zone
   from infra.firewall import firewall, firewall_public_ip
   from infra.monitoring import workspace_analytics
   ```
   and in `__all__`:
   ```text
   "db_admin_password",
   "firewall",
   "firewall_public_ip",
   "mem_alert",
   "monitoring_dns_zone",
   "network_interface",
   ```
   Then:
   ```sh
   git add __main__.py infra/__init__.py
   git commit
   ```

4. **Fix the firewall allow-list so it matches what this VM actually needs** (see "The compatibility problem" above). Add these five rules to the `rules` list of the existing `workspaces-allow-restricted` collection in `infra/firewall.py`, right after `AllowRStudioDeb`:
   ```text
   network.AzureFirewallApplicationRuleArgs(
       description="Allow Ubuntu package archives used by cloud-init",
       name="AllowUbuntuArchive",
       protocols=[
           network.AzureFirewallApplicationRuleProtocolArgs(
               port=80,
               protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTP,
           ),
       ],
       source_addresses=vm_subnet.address_prefixes,
       target_fqdns=[
           "azure.archive.ubuntu.com",
           "archive.ubuntu.com",
           "security.ubuntu.com",
           "changelogs.ubuntu.com",
       ],
   ),
   network.AzureFirewallApplicationRuleArgs(
       description="Allow the VS Code apt repo used by cloud-init",
       name="AllowVsCodeRepo",
       protocols=[
           network.AzureFirewallApplicationRuleProtocolArgs(
               port=443,
               protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTPS,
           ),
       ],
       source_addresses=vm_subnet.address_prefixes,
       target_fqdns=[
           "packages.microsoft.com",
       ],
   ),
   network.AzureFirewallApplicationRuleArgs(
       description="Allow the Google Chrome apt repo used by cloud-init",
       name="AllowChromeRepo",
       protocols=[
           network.AzureFirewallApplicationRuleProtocolArgs(
               port=443,
               protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTPS,
           ),
       ],
       source_addresses=vm_subnet.address_prefixes,
       target_fqdns=[
           "dl.google.com",
       ],
   ),
   network.AzureFirewallApplicationRuleArgs(
       description="Allow the Azure SQL Database public endpoint",
       name="AllowAzureSql",
       protocols=[
           network.AzureFirewallApplicationRuleProtocolArgs(
               port=1433,
               protocol_type=network.AzureFirewallApplicationRuleProtocolType.MSSQL,
           ),
       ],
       source_addresses=vm_subnet.address_prefixes,
       target_fqdns=[
           "*.database.windows.net",
       ],
   ),
   network.AzureFirewallApplicationRuleArgs(
       description="Allow the Azure Storage public blob endpoint",
       name="AllowAzureStorage",
       protocols=[
           network.AzureFirewallApplicationRuleProtocolArgs(
               port=443,
               protocol_type=network.AzureFirewallApplicationRuleProtocolType.HTTPS,
           ),
       ],
       source_addresses=vm_subnet.address_prefixes,
       target_fqdns=[
           "*.blob.core.windows.net",
       ],
   ),
   ```
   Leave PR #7's original three allow rules and the deny collection untouched — they're harmless, and removing them isn't necessary to fix the actual break.

5. **Close the test coverage gap.** PR #7 adds zero tests for `infra/firewall.py` or the `route_table` addition to `infra/networking.py`. Add `tests/test_firewall.py` and extend `tests/test_networking.py`, mirroring this repo's existing style. As with the previous two consolidations, this was written and run against the merged-plus-fixed code in a disposable worktree to confirm it passes; the same mocking quirk from the Log Analytics consolidation applies here too — nested Args come back as plain `dict`s, and a few input-only fields (e.g. `Route.route_table_name`, NAT/application rules' `source_addresses` on some but not all rule types) aren't exposed as output attributes at all, so those aren't asserted on.

   `tests/test_firewall.py`:
   ```python
   """Tests for infra.firewall using Pulumi's mocking framework."""

   import unittest

   import pulumi

   from infra.firewall import firewall, firewall_public_ip, route


   class TestFirewall(unittest.TestCase):
       @pulumi.runtime.test
       def test_firewall_urn(self):
           def check_urn(urn: str) -> None:
               self.assertIn("rse-firewall", urn)

           return firewall.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_firewall_uses_basic_sku(self):
           def check(sku) -> None:
               self.assertEqual(sku["tier"], "Basic")

           return firewall.sku.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_firewall_public_ip_is_standard_sku_with_static_allocation(self):
           def check(args: tuple) -> None:
               sku, allocation_method = args
               self.assertEqual(sku["name"], "Standard")
               self.assertEqual(allocation_method, "Static")

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               firewall_public_ip.sku, firewall_public_ip.public_ip_allocation_method
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_nat_rule_forwards_ssh_from_the_documented_source_ip(self):
           def check(nat_rule_collections: list) -> None:
               self.assertEqual(len(nat_rule_collections), 1)
               rule = nat_rule_collections[0]["rules"][0]
               self.assertEqual(rule["source_addresses"], ["193.60.220.253"])
               self.assertEqual(rule["destination_ports"], ["22"])
               self.assertEqual(rule["translated_port"], "22")

           return firewall.nat_rule_collections.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )

       @pulumi.runtime.test
       def test_application_rules_allow_this_vms_cloud_init_dependencies(self):
           def check(application_rule_collections: list) -> None:
               allow_collection = next(
                   collection
                   for collection in application_rule_collections
                   if collection["name"] == "workspaces-allow-restricted"
               )
               fqdns_by_rule_name = {
                   rule["name"]: set(rule["target_fqdns"])
                   for rule in allow_collection["rules"]
               }
               self.assertTrue(
                   {"archive.ubuntu.com", "security.ubuntu.com"}.issubset(
                       fqdns_by_rule_name["AllowUbuntuArchive"]
                   )
               )
               self.assertIn(
                   "packages.microsoft.com", fqdns_by_rule_name["AllowVsCodeRepo"]
               )
               self.assertIn("dl.google.com", fqdns_by_rule_name["AllowChromeRepo"])
               self.assertIn("*.database.windows.net", fqdns_by_rule_name["AllowAzureSql"])
               self.assertIn(
                   "*.blob.core.windows.net", fqdns_by_rule_name["AllowAzureStorage"]
               )

           return firewall.application_rule_collections.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )

       @pulumi.runtime.test
       def test_application_rules_deny_snapcraft_upload_and_login(self):
           def check(application_rule_collections: list) -> None:
               deny_collection = next(
                   collection
                   for collection in application_rule_collections
                   if collection["name"] == "workspaces-deny"
               )
               self.assertEqual(deny_collection["action"]["type"], "Deny")
               rule = deny_collection["rules"][0]
               self.assertEqual(
                   set(rule["target_fqdns"]),
                   {
                       "dashboard.snapcraft.io",
                       "login.ubuntu.com",
                       "upload.apps.ubuntu.com",
                   },
               )

           return firewall.application_rule_collections.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )

       @pulumi.runtime.test
       def test_route_sends_all_traffic_via_the_firewall(self):
           def check(args: tuple) -> None:
               address_prefix, next_hop_type = args
               self.assertEqual(address_prefix, "0.0.0.0/0")
               self.assertEqual(next_hop_type, "VirtualAppliance")

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               route.address_prefix, route.next_hop_type
           ).apply(check)  # ty: ignore[invalid-argument-type]
   ```

   Addition to `tests/test_networking.py` (new import plus one new test method, inserted before the existing `test_vm_has_no_public_ip`):
   ```python
   from infra.networking import (
       network_interface,
       network_security_group,
       route_table,
       virtual_network,
       vm_subnet,
   )
   ```
   ```python
   @pulumi.runtime.test
   def test_vm_subnet_uses_the_route_table(self):
       def check(args: tuple) -> None:
           subnet_route_table_id, route_table_id = args
           self.assertEqual(subnet_route_table_id, route_table_id)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           vm_subnet.route_table.id, route_table.id
       ).apply(check)  # ty: ignore[invalid-argument-type]
   ```

   Confirmed in the disposable worktree: 8 new tests pass (7 in `test_firewall.py`, 1 added to `test_networking.py`), `ruff check`/`ruff format --check`/`ty check` are clean across every new and touched file, and the full suite (60 tests: the existing 52 plus these 8) passes.

6. **Update `README.md`'s "Project structure" section**, and **`README-Firewall.md`**, to reflect the fix and the Bastion coexistence:
   - Add a `firewall.py` bullet and `test_firewall.py` to the `tests/` bullet's list.
   - Update the existing `networking.py` bullet, which currently says the VM "is only reachable via the Bastion host" — no longer fully accurate once the firewall's NAT rule lands too:
     ```markdown
     - `networking.py` — VNet, subnet, NIC, and route table for the virtual machine (no public IP — the VM is reachable via the Bastion host or, for the narrower demo path described in `README-Firewall.md`, via the firewall's NAT rule; see below)
     - `firewall.py` — the Azure Firewall, its subnets/public IPs, the NAT rule that forwards SSH to the VM, the application rules restricting the VM's outbound access, and the route sending the VM subnet's traffic through the firewall
     ```
   - In `README-Firewall.md`, fix the pre-existing `infra/firewally.py` typo (two occurrences — should read `infra/firewall.py`).
   - In `README-Firewall.md`'s "Define Firewall application rules" section, document the five rules added in step 4 and the residual VS Code Marketplace gap (see "The compatibility problem" above for the exact wording used).
   - In `README-Firewall.md`'s "Connecting to the Virtual Machine" section, replace the opening sentence (which reads as if the firewall's public IP were the *only* way in) with a note that Bastion is still the general-purpose path and this NAT rule is a narrower, coexisting alternative.

7. **Manual verification that the merge itself is correct.**
   ```sh
   git log --oneline -5                          # merge commit + "Add Application Firewall to VM" both present
   git status                                     # working tree clean, no leftover conflict markers
   grep -rn "^<<<<<<<\|^=======\|^>>>>>>>" --include='*.py' .   # no unresolved conflict markers
   git diff origin/04-firewall consolidation -- infra/firewall.py README-Firewall.md
                                                   # should show only the step-4 rule additions and the
                                                   # step-6 doc fixes, nothing else
   ```

8. **Manual verification that the Pulumi program actually implements the firewall end-to-end.** This step involves `pulumi preview`/`pulumi up`, which per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) is **run by the user, not Claude** — unit tests and static checks are as far as automated verification goes here, and they cannot actually confirm the firewall's FQDN filtering behaves as intended (that depends on live DNS/SNI inspection, which nothing in this repo's test suite touches). Budget real time for this: PR #7's own `README-Firewall.md` notes an Azure Firewall can take tens of minutes to deploy.
   - `pulumi preview` first — this changes `vm_subnet` (adds a route table) and is a genuinely new set of resources (firewall, its subnets/IPs, the route); read the diff and confirm nothing unexpected is being replaced.
   - `pulumi up`, then confirm in the Azure Portal (or `az resource list --resource-group rse-cloud-cybersecurity-rg -o table`) that the firewall, its two public IPs, its two subnets, and the route table all exist, and that `rse-vm-subnet`'s effective routes show `0.0.0.0/0` pointed at the firewall's private IP.
   - **Watch cloud-init actually succeed.** Connect via Bastion (per `README-Bastion.md`) and check `/var/log/cloud-init-output.log` — confirm the `apt-get install` steps for `xfce4`/`xrdp`, then for `code`, then for `google-chrome-stable`, all complete without DNS/connection failures. If any step still fails, the blocked host will be in that log; add it to `infra/firewall.py`'s allow-list and redeploy.
   - Confirm the documented SQL/Storage workflows in `README.md` still work: open the pre-created `mssql` connection profile in VS Code and connect (exercises `*.database.windows.net`), and attach the Storage Account via the Azure Storage extension (exercises `*.blob.core.windows.net`).
   - Optionally, follow `README-Firewall.md`'s NAT-rule SSH path (`ssh azureuser@$(pulumi stack output firewall_public_ip)`) from the configured source IP, to confirm it still works alongside Bastion.
   - Optionally, confirm the firewall's deny rule actually blocks what it claims to (e.g. that `dashboard.snapcraft.io` is unreachable from the VM).

## Verification checklist

- [ ] `git merge origin/04-firewall` completes (with the two expected conflicts in `__main__.py` and `infra/__init__.py` resolved per steps 2–3).
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes, including the new `tests/test_firewall.py` and the new test added to `tests/test_networking.py` (60 tests total).
- [ ] `infra/firewall.py`'s `workspaces-allow-restricted` collection includes the five added rules (Ubuntu archives, VS Code repo, Chrome repo, Azure SQL, Azure Storage) alongside PR #7's original three.
- [ ] `__main__.py` no longer imports/exports the stale `public_ip`/`vm_public_ip` — it exports `firewall_public_ip` alongside the existing Bastion exports.
- [ ] `README.md`'s project structure section lists `firewall.py` and `test_firewall.py`, and no longer implies Bastion is the VM's only access path.
- [ ] `README-Firewall.md` no longer has the `infra/firewally.py` typo, documents the five added rules and the VS Code Marketplace gap, and no longer implies its NAT rule is the only way to reach the VM.
- [ ] (Manual, by the user) `git log`/`git status`/the targeted `git diff` in step 7 confirm the merge captured every file PR #7 touches, with no leftover conflict markers and no unintended drift beyond this plan's fixes.
- [ ] (Manual, by the user) `pulumi preview`/`pulumi up` succeed against the `dev` stack; the firewall and its supporting resources exist as designed, and `rse-vm-subnet`'s effective route table sends `0.0.0.0/0` to the firewall.
- [ ] (Manual, by the user) Cloud-init completes successfully end-to-end on a fresh deploy (checked via `/var/log/cloud-init-output.log`), with no packages blocked by the firewall.
- [ ] (Manual, by the user) The documented SQL Database and Storage Account workflows in `README.md` still work with the firewall in place.

## Out of scope for this document

- Anything from PRs #8, #9 (managed identity, storage firewall) — this plan only covers bringing PR #7 into `consolidation`, on top of the Bastion and Log Analytics work already there. Later consolidation passes for those PRs get their own plan documents.
- Pinning down the exact VS Code Marketplace CDN endpoint set. This is flagged as a known residual gap (see "The compatibility problem" and `README-Firewall.md`'s updated text) rather than guessed at, since it isn't a fixed, documented list and can't be confirmed without a live deployment.
- Deciding between the Bastion and Firewall-NAT-rule access paths, or removing either. Both are kept, as a deliberate demonstration of two different access patterns; this is a design/demo-content decision for the user, not a consolidation blocker.
- Claude running `pulumi preview`/`pulumi up` itself — per [CLAUDE.md](../CLAUDE.md), that's the user's to run manually (step 8 above is written for the user to execute, not for Claude to automate).
