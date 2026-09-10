# Consolidating Log Analytics — PR #5

Plan to bring [PR #5 "Add Log Analytics Workspace"](https://github.com/alan-turing-institute/rse-cloud-cybersecurity/pull/5) (branch `03-log-analytics`) into `consolidation`, so the resulting branch still passes the project's verification gate (`ruff check`, `ruff format --check`, `ty check`, `pytest` — see [`CLAUDE.md`](../CLAUDE.md)), without breaking the Bastion work already on `consolidation` ([`consolidating-bastion.md`](consolidating-bastion.md)).

## Starting point

- `consolidation`'s current tip (`8dff11b`) already has PR #3 (Bastion) folded in.
- `03-log-analytics` (`a17e702`) branches from `728d52e` — the same commit `consolidation` itself started from, *before* the Bastion and README-role-assignment work landed on top of it. So, unlike PR #3, this **will not be a fast-forward**: `git merge` produces a real merge commit with one conflict.
- A dry-run merge (`git merge-tree`, and a full merge attempt in a disposable `git worktree`) confirms exactly one textual conflict, in `infra/__init__.py` — both branches add their own import/re-export lines around the same location. `infra/compute.py` is touched by both PR #3 (indirectly, via `networking.py`) and PR #5, but merges automatically with no conflict since PR #3 never touched `compute.py`. Every other file PR #5 adds (`README-LogAnalytics.md`, `infra/alerts.py`, `infra/dns.py`, `infra/monitoring.py`) is untouched by anything already on `consolidation`, so those merge in cleanly as new files.
- The full merge (conflict resolved as below) was verified end-to-end in a disposable worktree: `ruff check`, `ruff format --check`, `ty check`, and `pytest` (with the new tests from step 4 added) all pass.

## What PR #5 changes

- Adds `infra/monitoring.py`: the Log Analytics `Workspace` (`workspace_analytics`, 30-day retention, PerGB2018 SKU), a `DataCollectionEndpoint` with public network access disabled, a `DataCollectionRule` collecting CPU/memory/disk perf counters and syslog, a private `PrivateLinkScope` linking the workspace and endpoint, a dedicated `/24` subnet, and a `PrivateEndpoint` into that subnet.
- Adds `infra/dns.py`: five private DNS zones (`privatelink.monitor.azure.com` and friends) with VNet links, plus a `PrivateDnsZoneGroup` tying them to the monitoring private endpoint.
- Adds `infra/alerts.py`: an `ActionGroup` (email notification) and two `MetricAlert`s — CPU > 90% and memory > 75%, both over a 5-minute window, both wired to the action group.
- Updates `infra/compute.py`: adds a system-assigned managed identity and boot diagnostics to the VM, attaches the `AzureMonitorLinuxAgent` VM extension, and associates the VM with the data collection rule and endpoint from `infra/monitoring.py`.
- Updates `infra/__init__.py`: re-exports `cpu_alert`, `monitoring_dns_zone`, `workspace_analytics` (does **not** re-export `mem_alert`, `data_collection_endpoint`, `data_collection_rule_vms`, etc. — see step 3).
- Adds `README-LogAnalytics.md`: a standalone write-up of the design (mirrors `README-Bastion.md`'s style) plus a "Viewing Logs" walkthrough.
- Adds **no tests** for any of this — `tests/`, `conftest.py`, and `pyproject.toml`/`uv.lock` are untouched by PR #5.

## Steps

1. **Merge, don't rebase.** From `consolidation`:
   ```sh
   git merge origin/03-log-analytics
   ```
   Unlike PR #3, expect this to stop with one conflict in `infra/__init__.py` (both branches add import lines at the same spot) — resolve it, don't abort. Keep both PRs' commit history intact; this becomes a real merge commit (two parents), which is expected and correct here.

2. **Resolve the `infra/__init__.py` conflict by keeping both sides.** Git leaves markers like:
   ```python
   <<<<<<< HEAD
   from infra.bastion import bastion_host
   from infra.bastion_networking import (
       bastion_public_ip,
   )
   =======
   from infra.alerts import cpu_alert
   >>>>>>> origin/03-log-analytics
   ```
   Resolve by keeping both import blocks, alphabetically ordered (matching the file's existing convention):
   ```python
   from infra.alerts import cpu_alert
   from infra.bastion import bastion_host
   from infra.bastion_networking import (
       bastion_public_ip,
   )
   ```
   The rest of the file (the `dns`/`monitoring` imports and the `__all__` list) auto-merges without conflict — Git already interleaves PR #5's `cpu_alert`, `monitoring_dns_zone`, `workspace_analytics` entries into the existing `bastion_host`/`bastion_public_ip` entries correctly, alphabetically. Then:
   ```sh
   git add infra/__init__.py
   git commit
   ```

3. **Fix two rough edges PR #5 introduces**, in the spirit of the export-name fix from the Bastion consolidation:

   a. **`infra/compute.py` sets a VM name that doesn't match the rest of the codebase.** The `VirtualMachine` resource is created as `compute.VirtualMachine("rse-vm", ...)` — every other reference to this machine (the Pulumi logical resource name, `os_profile.computer_name="rse-vm"`, `README.md`, `specs/01-the-scenario.md`) uses `rse-vm`. PR #5 adds `vm_name="rse-vm-workspace-vm"`, which overrides the *actual Azure resource name* to something else entirely (almost certainly copy-pasted from an unrelated example). Left in place, this silently renames the deployed VM the first time `consolidation` is applied on top of an existing `main` deployment — since a VM's name is immutable in Azure, that's a delete-and-recreate, not an in-place update. Remove the line:
      ```text
      identity=compute.VirtualMachineIdentityArgs(
          type=compute.ResourceIdentityType.SYSTEM_ASSIGNED,
      ),
      ```
      i.e. drop `vm_name="rse-vm-workspace-vm",` entirely so the VM keeps its existing `rse-vm` name.

   b. **`mem_alert` isn't re-exported from `infra/__init__.py`**, even though its sibling `cpu_alert` is. Nothing outside `infra/alerts.py` currently needs `mem_alert`, but leaving it out is an inconsistency worth closing while touching this file anyway:
      ```python
      from infra.alerts import cpu_alert, mem_alert
      ```
      and in `__all__`:
      ```text
      "db_admin_password",
      "mem_alert",
      "monitoring_dns_zone",
      ```

4. **Close the test coverage gap.** PR #5 adds zero tests for `infra/monitoring.py`, `infra/alerts.py`, `infra/dns.py`, or the new parts of `infra/compute.py`. As with the Bastion consolidation, add tests mirroring this repo's existing style (`pulumi.runtime.test` + `Output.apply`/`Output.all`, one `TestCase` per module). Two of the three new resources this touches — `VirtualMachineExtension` and the two `DataCollectionRuleAssociation`s in `compute.py`, and the two `PrivateLinkScopedResource`s in `monitoring.py` — were created as anonymous expression statements (not bound to a name), which makes them untestable from outside the module; bind them to module-level names first (purely additive, no behavioural change):

   In `infra/compute.py` (excerpt — only the left-hand side of each assignment changes):
   ```text
   azure_monitor_extension = compute.VirtualMachineExtension(
       "rse-azure-monitor-extension",
       ...
   )
   ...
   data_collection_rule_association = monitor.DataCollectionRuleAssociation(
       "rse-dcra-to-dcr",
       ...
   )
   ...
   data_collection_endpoint_association = monitor.DataCollectionRuleAssociation(
       "rse-dcra-to-dce",
       ...
   )
   ```

   In `infra/monitoring.py` (same excerpt convention):
   ```text
   workspace_private_link_connection = monitor.PrivateLinkScopedResource(
       "rse-log-analytics-ampls-connection",
       ...
   )
   ...
   data_collection_endpoint_private_link_connection = monitor.PrivateLinkScopedResource(
       "rse-data-collection-endpoint-ampls-connection",
       ...
   )
   ```

   All of the following was written and run against the merged code (in a disposable `git worktree`, using `uv run pytest`/`ruff`/`ty` — no live Azure calls) to confirm it passes. One implementation note that fell out of writing these: the shared `AzureMocks` in `conftest.py` echoes raw input dicts back as outputs, so nested Args objects come back as plain `dict`s (sometimes snake_case, sometimes camelCase, depending on the resource type's SDK-generated shape) rather than typed objects — hence the mix of `.attr` and `["key"]` access below; each was checked against the actual mocked shape, not assumed.

   `tests/test_monitoring.py`:
   ```python
   """Tests for infra.monitoring using Pulumi's mocking framework."""

   import unittest

   import pulumi

   from infra.monitoring import (
       data_collection_endpoint,
       data_collection_rule_vms,
       log_analytics_private_endpoint,
       log_analytics_private_link_scope,
       subnet_monitoring,
       workspace_analytics,
   )


   class TestMonitoring(unittest.TestCase):
       @pulumi.runtime.test
       def test_workspace_analytics_urn(self):
           def check_urn(urn: str) -> None:
               self.assertIn("rse-log-analytics", urn)

           return workspace_analytics.urn.apply(check_urn)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_workspace_analytics_retention_and_sku(self):
           def check(args: tuple) -> None:
               retention_in_days, sku = args
               self.assertEqual(retention_in_days, 30)
               self.assertEqual(sku["name"], "PerGB2018")

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               workspace_analytics.retention_in_days, workspace_analytics.sku
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_data_collection_endpoint_disables_public_network_access(self):
           def check(network_acls) -> None:
               self.assertEqual(network_acls.public_network_access, "Disabled")

           return data_collection_endpoint.network_acls.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )

       @pulumi.runtime.test
       def test_data_collection_rule_sends_perf_and_syslog_to_the_workspace(self):
           def check(args: tuple) -> None:
               destinations, data_flows = args
               self.assertEqual(len(destinations["log_analytics"]), 1)
               streams = {stream for flow in data_flows for stream in flow["streams"]}
               self.assertEqual(streams, {"Microsoft-Perf", "Microsoft-Syslog"})

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               data_collection_rule_vms.destinations, data_collection_rule_vms.data_flows
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_data_collection_rule_collects_cpu_and_memory_perf_counters(self):
           def check(data_sources: dict) -> None:
               counters = data_sources["performance_counters"][0]["counter_specifiers"]
               self.assertIn("Processor(*)\\% Processor Time", counters)
               self.assertIn("Memory(*)\\% Used Memory", counters)

           return data_collection_rule_vms.data_sources.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )

       @pulumi.runtime.test
       def test_private_link_scope_is_private_only(self):
           def check(access_mode_settings) -> None:
               self.assertEqual(access_mode_settings.ingestion_access_mode, "PrivateOnly")
               self.assertEqual(access_mode_settings.query_access_mode, "PrivateOnly")

           return log_analytics_private_link_scope.access_mode_settings.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )

       @pulumi.runtime.test
       def test_monitoring_subnet_uses_a_distinct_address_space(self):
           def check(address_prefix: str) -> None:
               self.assertEqual(address_prefix, "10.0.3.0/24")

           return subnet_monitoring.address_prefix.apply(check)  # ty: ignore[missing-argument, invalid-argument-type]

       @pulumi.runtime.test
       def test_log_analytics_private_endpoint_uses_the_monitoring_subnet(self):
           def check(args: tuple) -> None:
               endpoint_subnet_id, subnet_id = args
               self.assertEqual(endpoint_subnet_id, subnet_id)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               log_analytics_private_endpoint.subnet.id, subnet_monitoring.id
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_log_analytics_private_endpoint_targets_azuremonitor(self):
           def check(connections: list) -> None:
               self.assertEqual(len(connections), 1)
               self.assertEqual(connections[0].group_ids, ["azuremonitor"])

           return log_analytics_private_endpoint.private_link_service_connections.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )
   ```

   `tests/test_alerts.py`:
   ```python
   """Tests for infra.alerts using Pulumi's mocking framework."""

   import unittest

   import pulumi

   from infra.alerts import action_group, cpu_alert, mem_alert


   class TestAlerts(unittest.TestCase):
       @pulumi.runtime.test
       def test_action_group_has_an_enabled_email_receiver(self):
           def check(args: tuple) -> None:
               enabled, email_receivers = args
               self.assertTrue(enabled)
               self.assertEqual(len(email_receivers), 1)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               action_group.enabled, action_group.email_receivers
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_cpu_alert_triggers_above_90_percent(self):
           def check(args: tuple) -> None:
               criteria, enabled, actions, action_group_id = args
               metric = criteria["allOf"][0]
               self.assertEqual(metric["metricName"], "Average_% Processor Time")
               self.assertEqual(metric["threshold"], 90)
               self.assertTrue(enabled)
               self.assertEqual(len(actions), 1)
               self.assertEqual(actions[0]["action_group_id"], action_group_id)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               cpu_alert.criteria, cpu_alert.enabled, cpu_alert.actions, action_group.id
           ).apply(check)  # ty: ignore[invalid-argument-type]

       @pulumi.runtime.test
       def test_mem_alert_triggers_above_75_percent(self):
           def check(args: tuple) -> None:
               criteria, enabled, actions, action_group_id = args
               metric = criteria["allOf"][0]
               self.assertEqual(metric["metricName"], "Average_% Used Memory")
               self.assertEqual(metric["threshold"], 75)
               self.assertTrue(enabled)
               self.assertEqual(len(actions), 1)
               self.assertEqual(actions[0]["action_group_id"], action_group_id)

           return pulumi.Output.all(  # ty: ignore[missing-argument]
               mem_alert.criteria, mem_alert.enabled, mem_alert.actions, action_group.id
           ).apply(check)  # ty: ignore[invalid-argument-type]
   ```

   `tests/test_dns.py`:
   ```python
   """Tests for infra.dns using Pulumi's mocking framework."""

   import unittest

   import pulumi

   from infra.dns import dns_zones, monitoring_dns_zone


   class TestDns(unittest.TestCase):
       def test_defines_the_five_monitoring_private_link_domains(self):
           self.assertEqual(
               set(dns_zones.values()),
               {
                   "privatelink.monitor.azure.com",
                   "privatelink.oms.opinsights.azure.com",
                   "privatelink.ods.opinsights.azure.com",
                   "privatelink.agentsvc.azure-automation.net",
                   "privatelink.blob.core.windows.net",
               },
           )

       @pulumi.runtime.test
       def test_monitoring_dns_zone_group_covers_every_domain(self):
           def check(configs: list) -> None:
               self.assertEqual(len(configs), len(dns_zones))
               names = {config.name for config in configs}
               self.assertEqual(names, {f"rse-log-to-{name}" for name in dns_zones})

           return monitoring_dns_zone.private_dns_zone_configs.apply(  # ty: ignore[missing-argument]
               check  # ty: ignore[invalid-argument-type]
           )
   ```

   Additions to `tests/test_compute.py` (new imports plus five new test methods, inserted after the existing `test_virtual_machine_uses_password_auth`):
   ```python
   from infra.compute import (
       azure_monitor_extension,
       data_collection_endpoint_association,
       data_collection_rule_association,
       virtual_machine,
   )
   from infra.monitoring import data_collection_endpoint, data_collection_rule_vms
   ```
   ```text
   @pulumi.runtime.test
   def test_virtual_machine_has_a_system_assigned_identity(self):
       def check(identity) -> None:
           self.assertEqual(identity.type, "SystemAssigned")

       return virtual_machine.identity.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )

   @pulumi.runtime.test
   def test_virtual_machine_enables_boot_diagnostics(self):
       def check(diagnostics_profile) -> None:
           self.assertTrue(diagnostics_profile.boot_diagnostics.enabled)

       return virtual_machine.diagnostics_profile.apply(  # ty: ignore[missing-argument]
           check  # ty: ignore[invalid-argument-type]
       )

   @pulumi.runtime.test
   def test_azure_monitor_extension_is_the_expected_agent(self):
       def check(args: tuple) -> None:
           publisher, extension_type = args
           self.assertEqual(publisher, "Microsoft.Azure.Monitor")
           self.assertEqual(extension_type, "AzureMonitorLinuxAgent")

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           azure_monitor_extension.publisher,
           azure_monitor_extension.type,
       ).apply(check)  # ty: ignore[invalid-argument-type]

   @pulumi.runtime.test
   def test_virtual_machine_is_associated_with_the_data_collection_rule_and_endpoint(
       self,
   ):
       def check(args: tuple) -> None:
           dcr_association_id, dcr_id, dce_association_id, dce_id = args
           self.assertEqual(dcr_association_id, dcr_id)
           self.assertEqual(dce_association_id, dce_id)

       return pulumi.Output.all(  # ty: ignore[missing-argument]
           data_collection_rule_association.data_collection_rule_id,
           data_collection_rule_vms.id,
           data_collection_endpoint_association.data_collection_endpoint_id,
           data_collection_endpoint.id,
       ).apply(check)  # ty: ignore[invalid-argument-type]
   ```

   Confirmed in the disposable worktree: 18 new tests pass (8 in `test_monitoring.py`, 3 in `test_alerts.py`, 2 in `test_dns.py`, 5 added to `test_compute.py`), `ruff check`/`ruff format --check`/`ty check` are clean across every new and touched file, and the full suite (52 tests: the existing 34 plus these 18) passes.

5. **Update `README.md`'s "Project structure" section** to list the three new `infra` modules, matching the level of detail already given for the others:
   ```markdown
   - `monitoring.py` — the Log Analytics workspace, data collection endpoint/rule, and the private-link plumbing (subnet, private endpoint, AMPLS scope) needed to reach it without public network access
   - `dns.py` — private DNS zones and VNet links so the VM can resolve the monitoring private endpoint
   - `alerts.py` — the action group and CPU/memory metric alerts built on top of the workspace
   ```
   Insert them after the existing `compute.py` bullet, and also update `tests/` bullet's test-file list to include `test_monitoring.py`, `test_alerts.py`, `test_dns.py`.

6. **Manual verification that the merge itself is correct.** Before moving on to deployment verification, confirm the merge commit on `consolidation` actually captured PR #5 in full and didn't silently drop anything:
   ```sh
   git log --oneline -5                          # merge commit + "Add Log Analytics Workspace" both present
   git status                                     # working tree clean, no leftover conflict markers
   grep -rn "^<<<<<<<\|^=======\|^>>>>>>>" --include='*.py' .   # no unresolved conflict markers
   git diff origin/03-log-analytics consolidation -- infra/monitoring.py infra/dns.py infra/alerts.py README-LogAnalytics.md
                                                   # should show only the two PrivateLinkScopedResource
                                                   # name-binding changes from step 4, nothing else
   ```

7. **Manual verification that the Pulumi program actually implements log collection end-to-end.** This step involves `pulumi preview`/`pulumi up`, which per [CLAUDE.md § No live deployments](../CLAUDE.md#no-live-deployments-as-part-of-building-a-feature) is **run by the user, not Claude** — unit tests and static checks are as far as automated verification goes here. Before running it:
   - **Change the placeholder email address.** `infra/alerts.py`'s own comment says as much: `email_address = "email @ example.com"` is deliberately invalid and documented to fail deployment as-is. Set it to a real address before `pulumi up`.
   - `pulumi preview` first, and read the diff carefully — this changes the VM resource itself (adds `identity`, `diagnostics_profile`) which Azure may report as requiring a VM restart or in-place update; confirm it isn't reported as a replace (it shouldn't be, since the VM's name/`computer_name` are unaffected once step 3a's fix is applied).
   - `pulumi up`, then confirm in the Azure Portal (or `az resource list --resource-group rse-cloud-cybersecurity-rg -o table`) that: a Log Analytics workspace `rse-log-analytics` exists with 30-day retention, a Data Collection Endpoint and Rule exist and are associated with `rse-vm`, the five private DNS zones and the monitoring private endpoint/subnet exist, and two metric alerts (CPU/memory) plus one action group exist.
   - Follow `README-LogAnalytics.md`'s "Viewing Logs" section: in the Azure Portal, open the `rse-log-analytics` workspace, run the "All Syslog" query under Virtual Machines, and confirm log rows actually arrive from `rse-vm` (this can take several minutes after the `AzureMonitorLinuxAgent` extension installs).
   - Optionally, verify the alerts fire: push CPU or memory above the threshold on the VM for 5+ minutes and confirm the action group's email arrives.

## Verification checklist

- [ ] `git merge origin/03-log-analytics` completes (with the one expected conflict in `infra/__init__.py` resolved per step 2).
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes, including the new `tests/test_monitoring.py`, `tests/test_alerts.py`, `tests/test_dns.py`, and the five new tests added to `tests/test_compute.py` (52 tests total).
- [ ] `infra/compute.py` no longer sets `vm_name="rse-vm-workspace-vm"` — the VM stays `rse-vm`.
- [ ] `infra/__init__.py` re-exports `mem_alert` alongside `cpu_alert`.
- [ ] `README.md`'s project structure section lists `monitoring.py`, `dns.py`, and `alerts.py`, and the `tests/` bullet lists the three new test modules.
- [ ] (Manual, by the user) `git log`/`git status`/the targeted `git diff` in step 6 confirm the merge captured every file PR #5 touches, with no leftover conflict markers and no unintended drift from PR #5's own code beyond this plan's fixes.
- [ ] (Manual, by the user) The placeholder email address in `infra/alerts.py` is changed to a real one before deploying.
- [ ] (Manual, by the user) `pulumi preview`/`pulumi up` succeed against the `dev` stack; the workspace, DCE/DCR, private DNS/endpoint, and alerts all exist as designed, and the VM isn't replaced.
- [ ] (Manual, by the user) Logs actually arrive in the Log Analytics workspace (`README-LogAnalytics.md`'s "All Syslog" query returns rows from `rse-vm`).

## Out of scope for this document

- Anything from PRs #7, #8, #9 (App Firewall, managed identity, storage firewall) — this plan only covers bringing PR #5 into `consolidation`, on top of the Bastion work already there. Later consolidation passes for those PRs get their own plan documents.
- New `__main__.py` stack outputs for the Log Analytics resources (e.g. `pulumi stack output`-able workspace/alert IDs). PR #5 doesn't add any, and adding them isn't needed to satisfy "bring the changes in without breaking existing functionality" — it's a reasonable follow-up, not a consolidation blocker.
- Claude running `pulumi preview`/`pulumi up` itself — per [CLAUDE.md](../CLAUDE.md), that's the user's to run manually (step 7 above is written for the user to execute, not for Claude to automate).
