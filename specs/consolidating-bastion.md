# Consolidating Bastion — PR #3

Plan to bring [PR #3 "Add Azure Bastion Host"](https://github.com/alan-turing-institute/rse-cloud-cybersecurity/pull/3) (branch `02-bastion-host`) into `consolidation`, so the resulting branch still passes the project's verification gate (`ruff check`, `ty check`, `pytest` — see [`CLAUDE.md`](../CLAUDE.md)).

## Starting point

- `consolidation` was branched from `main` (`98b979f`) and currently has no other content merged into it yet.
- `02-bastion-host` (`dc36a10`) is a single commit on top of the same `main` commit — no divergence between the two branches' common ancestor and `consolidation`'s current tip.
- A dry-run merge (`git merge-tree`) between `consolidation` and `origin/02-bastion-host` produces no conflicts. This should be a clean merge, not a rebase/cherry-pick exercise.

## What PR #3 changes

- Removes the VM's public IP (`infra/networking.py`): drops the `public_ip` resource and the NIC's reference to it.
- Adds `infra/bastion_networking.py`: a dedicated NSG (`bastion_network_security_group`) with the inbound/outbound rules Azure Bastion requires, an `AzureBastionSubnet` (`bastion_subnet`, `10.0.2.0/24`), and a Standard/static public IP (`bastion_public_ip`).
- Adds `infra/bastion.py`: the `BastionHost` resource itself (`bastion_host`), Standard SKU, wired to the subnet + public IP above, with tunneling and shareable links enabled.
- Updates `infra/__init__.py` re-exports: drops `public_ip`, adds `bastion_host`, `bastion_public_ip`.
- Updates `__main__.py`: drops the `vm_public_ip` export, adds `vm_id`, `bastion_name`, `bastion_id`, `bastion_public_ip` exports.
- Updates `tests/test_networking.py`: replaces `test_public_ip_is_standard_sku_with_static_allocation` with `test_vm_has_no_public_ip`, which asserts the VM's NIC IP configuration carries no `public_ip_address`.
- Adds `README-Bastion.md`: a standalone write-up of the design and connection instructions (SSH/RDP via `az network bastion`, shareable links).

## Steps

1. **Merge, don't rebase.** From `consolidation`:
   ```sh
   git merge origin/02-bastion-host
   ```
   Expect a clean merge (no conflicts, per the dry run above). Do not squash or cherry-pick — keep the PR's commit history intact so `git log` on `consolidation` still shows where the bastion work came from.

2. **Verify with the project's standard gate** (no live deployment — see [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature)):
   ```sh
   uv run ruff check .
   uv run ruff format --check .
   uv run ty check
   uv run pytest
   ```
   PR #3's own CI run already passed these checks in isolation; re-running them on `consolidation` confirms nothing about the merge (e.g. import ordering in `infra/__init__.py`, re-export lists) broke once its history lands on top of `consolidation`'s tip.

3. **Fix the swapped stack-output names introduced by PR #3.** In `__main__.py`, the bastion exports are mislabeled relative to what they actually hold and what `README-Bastion.md` describes:
   ```python
   pulumi.export(
       "bastion_name", bastion_public_ip.ip_address
   )  # holds an IP address, not a name
   pulumi.export("bastion_id", bastion_host.id)
   pulumi.export(
       "bastion_public_ip", bastion_host.name
   )  # holds the host's name, not its IP
   ```
   `README-Bastion.md` documents `pulumi stack output bastion_id` and treats the bastion's public IP as the thing an operator would want under `bastion_public_ip`. Swap the two so the export names match their values:
   ```python
   pulumi.export("bastion_name", bastion_host.name)
   pulumi.export("bastion_id", bastion_host.id)
   pulumi.export("bastion_public_ip", bastion_public_ip.ip_address)
   ```
   This doesn't affect `pulumi preview`/deployment success (no test currently covers these export names), but leaving it in place would ship a confusing/incorrect stack output on `consolidation`.

4. **Update `README.md`'s "Project structure" section** to list the two new `infra` modules, matching the level of detail already given for `networking.py`, `storage.py`, etc.:
   ```markdown
   - `bastion_networking.py` — NSG, subnet, and public IP for the Azure Bastion host
   - `bastion.py` — the Azure Bastion host itself
   ```
   Also update the `networking.py` bullet — it currently says "VNet, subnet, public IP, and NIC for the virtual machine," which is no longer accurate once the VM's public IP is removed (the public IP that remains is the bastion's, defined in `bastion_networking.py`).

5. **Close the test coverage gap: add `tests/test_bastion_networking.py` and `tests/test_bastion.py`.** PR #3 adds no tests of its own for the new NSG rules, subnet, public IP, or `BastionHost` resource (only the VM's *lack* of a public IP is asserted, via the updated `test_networking.py`). The test code below was written and run against PR #3's actual code (in a disposable `git worktree` at `origin/02-bastion-host`, using `uv run pytest`/`ruff`/`ty` — no live Azure calls) to confirm it passes as-is; it mirrors the existing `test_networking.py`/`test_compute.py` style (one `TestCase` per module, `pulumi.runtime.test` + `Output.apply`/`Output.all`).

   `tests/test_bastion_networking.py`:
   ```python
   """Tests for infra.bastion_networking using Pulumi's mocking framework."""

   import unittest

   import pulumi

   from infra.bastion_networking import (
       bastion_network_security_group,
       bastion_public_ip,
       bastion_subnet,
   )
   from infra.networking import vm_subnet


   class TestBastionNetworking(unittest.TestCase):
       @pulumi.runtime.test
       def test_bastion_subnet_is_named_azurebastionsubnet(self):
           def check_urn(urn: str) -> None:
               # Azure requires this exact name - Bastion deployment fails otherwise.
               self.assertIn("AzureBastionSubnet", urn)

           return bastion_subnet.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_subnet_uses_a_distinct_address_space_from_the_vm_subnet(self):
           def check(args: tuple) -> None:
               bastion_prefix, vm_prefix = args
               self.assertNotEqual(bastion_prefix, vm_prefix)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               bastion_subnet.address_prefix, vm_subnet.address_prefix
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_subnet_uses_the_bastion_network_security_group(self):
           def check(args: tuple) -> None:
               subnet_nsg_id, nsg_id = args
               self.assertEqual(subnet_nsg_id, nsg_id)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               bastion_subnet.network_security_group.id,
               bastion_network_security_group.id,
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_public_ip_is_standard_sku_with_static_allocation(self):
           def check(args: tuple) -> None:
               sku, allocation_method = args
               self.assertEqual(sku["name"], "Standard")
               self.assertEqual(allocation_method, "Static")

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               bastion_public_ip.sku, bastion_public_ip.public_ip_allocation_method
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_nsg_allows_https_inbound_from_internet(self):
           def check(security_rules: list) -> None:
               rules_by_name = {rule.name: rule for rule in security_rules}
               rule = rules_by_name["allow-http-inbound"]
               self.assertEqual(rule.direction, "Inbound")
               self.assertEqual(rule.access, "Allow")
               self.assertEqual(rule.destination_port_range, "443")
               self.assertEqual(rule.source_address_prefix, "Internet")

           return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_nsg_allows_control_plane_management_traffic(self):
           def check(security_rules: list) -> None:
               rules_by_name = {rule.name: rule for rule in security_rules}
               rule = rules_by_name["allow-gateway-manager-inbound"]
               self.assertEqual(rule.direction, "Inbound")
               self.assertEqual(rule.access, "Allow")
               self.assertEqual(rule.destination_port_range, "443")
               self.assertEqual(rule.source_address_prefix, "GatewayManager")

           return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_nsg_allows_outbound_ssh_and_rdp_to_the_target_subnet(self):
           def check(security_rules: list) -> None:
               rules_by_name = {rule.name: rule for rule in security_rules}
               for name, port in (
                   ("allow-ssh-outbound", "22"),
                   ("allow-rdp-outbound", "3389"),
               ):
                   rule = rules_by_name[name]
                   self.assertEqual(rule.direction, "Outbound")
                   self.assertEqual(rule.access, "Allow")
                   self.assertEqual(rule.destination_port_range, port)
                   self.assertEqual(rule.destination_address_prefix, "VirtualNetwork")

           return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_nsg_has_all_eleven_mandatory_rules(self):
           # Microsoft documents this rule set as mandatory - Bastion deployment
           # fails if any of them is missing. See README-Bastion.md's references.
           def check(security_rules: list) -> None:
               self.assertEqual(len(security_rules), 11)

           return bastion_network_security_group.security_rules.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]
   ```

   `tests/test_bastion.py`:
   ```python
   """Tests for infra.bastion using Pulumi's mocking framework."""

   import unittest

   import pulumi

   from infra.bastion import bastion_host
   from infra.bastion_networking import bastion_public_ip, bastion_subnet


   class TestBastion(unittest.TestCase):
       @pulumi.runtime.test
       def test_bastion_host_urn(self):
           def check_urn(urn: str) -> None:
               self.assertIn("rse-bastion", urn)

           return bastion_host.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_host_uses_standard_sku(self):
           def check(sku) -> None:
               self.assertEqual(sku["name"], "Standard")

           return bastion_host.sku.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_host_enables_tunneling_and_shareable_link(self):
           def check(args: tuple) -> None:
               enable_tunneling, enable_shareable_link = args
               self.assertTrue(enable_tunneling)
               self.assertTrue(enable_shareable_link)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               bastion_host.enable_tunneling, bastion_host.enable_shareable_link
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_bastion_host_uses_the_bastion_subnet_and_public_ip(self):
           def check(args: tuple) -> None:
               ip_configurations, subnet_id, public_ip_id = args
               self.assertEqual(len(ip_configurations), 1)
               configuration = ip_configurations[0]
               self.assertEqual(configuration["subnet"]["id"], subnet_id)
               self.assertEqual(configuration["public_ip_address"]["id"], public_ip_id)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               bastion_host.ip_configurations, bastion_subnet.id, bastion_public_ip.id
           ).apply(check)  # ty: ignore[invalid-argument-type]
   ```

   Confirmed in the disposable worktree: 12 new tests pass, `ruff check`/`ruff format --check`/`ty check` are clean on both files, and the full suite (34 tests) passes with these added.

6. **Manual verification that the merge itself is correct.** Before moving on to deployment verification, confirm the merge commit on `consolidation` actually captured PR #3 in full and didn't silently drop anything:
   ```sh
   git log --oneline -5                        # merge commit + "Add Azure Bastion Host" both present
   git diff main consolidation --stat           # should match PR #3's file list: __main__.py,
                                                 # infra/__init__.py, infra/bastion.py (new),
                                                 # infra/bastion_networking.py (new),
                                                 # infra/networking.py, tests/test_networking.py,
                                                 # README-Bastion.md (new), plus the two new test
                                                 # files and README.md from steps 3-5
   git status                                   # working tree clean, no leftover conflict markers
   grep -rn "^<<<<<<<\|^=======\|^>>>>>>>" --include='*.py' .   # no unresolved conflict markers
   ```

7. **Manual verification that the Pulumi program actually implements the bastion feature end-to-end.** This step involves `pulumi preview`/`pulumi up`, which per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) is **run by the user, not Claude** — unit tests and static checks are as far as automated verification goes here. Once `consolidation` is deployed (or updated from a prior deploy of `main`) to the `dev` stack:
   - `pulumi preview` first, and read the diff carefully — since this changes the VM's NIC (removing its public IP association), confirm whether Azure reports this as an in-place update or a replace of the NIC; either is fine, but it shouldn't be a surprise once `pulumi up` runs.
   - `pulumi up`, then confirm in the Azure Portal (or `az resource list --resource-group rse-cloud-cybersecurity-rg -o table`) that: the VM (`rse-vm`) has no public IP address attached, an `AzureBastionSubnet` (`10.0.2.0/24`) exists in the VNet, a Bastion resource (`rse-bastion-resource`) exists with a Standard SKU and a Standard/static public IP, and the bastion's NSG has all 11 rules from `infra/bastion_networking.py`.
   - Check the stack outputs make sense post-fix (step 3): `pulumi stack output bastion_name`, `pulumi stack output bastion_id`, `pulumi stack output bastion_public_ip`, `pulumi stack output vm_id` — confirm `bastion_public_ip` is actually an IP address and `bastion_name` is actually a name, not swapped. Confirm `vm_public_ip` is no longer a stack output (it's intentionally removed).
   - Follow `README-Bastion.md`'s connection instructions end-to-end: install the `bastion`/`ssh` `az` CLI extensions, retrieve `vm_admin_password` via `pulumi stack output vm_admin_password --show-secrets`, and confirm `az network bastion ssh --ids $BASTION_ID --target-resource-id $VM_ID --auth-type password --username azureuser` actually reaches the VM. This is the real end-to-end proof that the feature works, not just that resources exist.
   - Optionally, exercise the shareable-link flow documented in the same file (`createShareableLinks`/`getShareableLinks`) if verifying that feature specifically matters for the demo.

## Verification checklist

- [ ] `git merge origin/02-bastion-host` completes with no conflicts.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes, including the new `test_vm_has_no_public_ip`, `tests/test_bastion_networking.py`, and `tests/test_bastion.py`.
- [ ] `__main__.py`'s `bastion_name`/`bastion_public_ip` exports hold the values their names describe.
- [ ] `README.md`'s project structure section lists `bastion_networking.py` and `bastion.py`, and no longer claims `networking.py` owns "the" public IP.
- [ ] (Manual, by the user) `git log`/`git diff main consolidation --stat` confirm the merge captured every file PR #3 (plus this plan's fixes) touches, with no leftover conflict markers.
- [ ] (Manual, by the user) `pulumi preview`/`pulumi up` succeed against the `dev` stack; the VM has no public IP, the Bastion host and its subnet/NSG/public IP exist as designed, and stack outputs hold correctly-labeled values.
- [ ] (Manual, by the user) An actual SSH (or RDP) connection to the VM through the Bastion host succeeds, per `README-Bastion.md`.

## Out of scope for this document

- Anything from PRs #5, #7, #8, #9 (Log Analytics, App Firewall, managed identity, storage firewall) — this plan only covers bringing PR #3 into `consolidation`. Later consolidation passes for those PRs get their own plan documents.
- Claude running `pulumi preview`/`pulumi up` itself — per [CLAUDE.md](../CLAUDE.md), that's the user's to run manually (step 7 above is written for the user to execute, not for Claude to automate).
