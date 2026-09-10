# Remove the Azure SQL Database

Plan to remove the Azure SQL Database entirely from this Pulumi program on `consolidation`, along with everything that exists only to support it (the VM's VS Code `mssql` extension/connection profile, the Application Firewall's `AllowAzureSql` rule, the `db-admin-username` stack config, and the `db_admin_password`/`sql_server_fqdn` stack outputs), and bring the documentation in line.

After this plan, the deployment is a storage account and a Linux VM — no database of any kind. `infra/database.py` is deleted outright, not deprecated or hollowed out.

## What's being removed and why it's self-contained

`infra/database.py` defines four things: `admin_username` (config `db-admin-username`, default `sqladmin`), `db_admin_password` (a `pulumi_random.RandomPassword`), `sql_server` (`sql.Server`, named `rse-cybersecurity-sql-<suffix>` via `infra.naming.suffix`), `sql_firewall_rule` (open `0.0.0.0`–`255.255.255.255` — see `specs/01-the-scenario.md`), and `sql_database` (`sql.Database`, Basic tier).

Nothing in `infra/monitoring.py`, `infra/alerts.py`, `infra/dns.py`, `infra/networking.py`, `infra/storage.py`, `infra/bastion.py`, `infra/bastion_networking.py`, or `infra/resource_group.py` imports from `infra.database` or references SQL at all. The only consumers are:

- **`infra/compute.py`** — imports `admin_username` (aliased `db_admin_username`) and `sql_database`, `sql_server`; uses them only to build the VS Code `mssql.connections` profile baked into cloud-init (`_vscode_settings_json`, `_MSSQL_PROFILE_NAME`) and as two of the three `Output`s `custom_data` waits on.
- **`infra/firewall.py`** — one self-contained `AllowAzureSql` application rule (port 1433, `*.database.windows.net`); nothing else references it.
- **`infra/__init__.py`** — re-exports all five `infra.database` names.
- **`__main__.py`** — imports `db_admin_password` and `sql_server` for two stack-output lines (`sql_server_fqdn`, `db_admin_password`); nothing downstream depends on those exports.
- **`tests/test_database.py`** — tests only `infra.database`'s own resources; the whole file goes.
- **`tests/test_compute.py`** — one test (`test_custom_data_pre_creates_the_mssql_connection_profile`) asserts on the `mssql.connections` profile in the rendered cloud-init.
- **`tests/test_firewall.py`** — one assertion (not a whole test) checks `AllowAzureSql`'s FQDN inside `test_application_rules_allow_this_vms_cloud_init_dependencies`.

`infra/naming.py`'s `suffix` is shared between `sql_server`'s name and `storage_account`'s name — removing the database doesn't remove `infra/naming.py` itself (the storage account still needs it), only its "storage accounts and SQL logical servers" docstring, which goes back to storage-account-only.

Per direction: the VS Code `mssql` extension and its pre-seeded connection profile are removed outright (not left installed-but-unconfigured), and the `AllowAzureSql` firewall rule is deleted outright (not left in place as unused defence-in-depth, unlike this repo's existing treatment of `AllowAzureStorage`) — there is nothing left for either to defend once the database itself is gone.

## Steps

### 1. Delete `infra/database.py`

```sh
git rm infra/database.py
```

### 2. `infra/compute.py` — drop the SQL/mssql wiring

- Module docstring: remove the SQL/mssql sentences (currently: *"VS Code, with the mssql extension, is the way to reach the SQL database (see specs/01-the-scenario.md - no managed identity/RBAC for the database yet)."* and the whole paragraph about the pre-created `mssql` connection profile). What's left is the storage-identity/BlobFuse2 paragraph (from the managed-identity consolidation) plus the password-auth note — no rewording needed there.
- Imports: remove `from infra.database import admin_username as db_admin_username` and `from infra.database import sql_database, sql_server`. Remove `import json` too — it's used only inside `_vscode_settings_json`, which is deleted below (confirm nothing else in the file uses `json` before removing the import).
- Remove `_MSSQL_PROFILE_NAME = "rse-demo-db"`.
- Delete `_vscode_settings_json` entirely.
- Simplify `_custom_data` and `custom_data` to drop the two SQL-derived arguments — only `storage_account_name` remains:
  ```python
  def _custom_data(storage_account_name: str) -> str:
      blobfuse2_config_yaml = _blobfuse2_config_template.render(
          storage_account_name=storage_account_name
      )
      blobfuse2_config_b64 = base64.b64encode(blobfuse2_config_yaml.encode()).decode()
      blobfuse2_unit = _blobfuse2_unit_template.render(
          mount_path=_BLOBFUSE2_MOUNT_PATH, config_path=_BLOBFUSE2_CONFIG_PATH
      )
      blobfuse2_unit_b64 = base64.b64encode(blobfuse2_unit.encode()).decode()
      cloud_init = _cloud_init_template.render(
          admin_username=admin_username,
          blobfuse2_config_b64=blobfuse2_config_b64,
          blobfuse2_unit_b64=blobfuse2_unit_b64,
          blobfuse2_config_path=_BLOBFUSE2_CONFIG_PATH,
          blobfuse2_mount_path=_BLOBFUSE2_MOUNT_PATH,
          blobfuse2_service_name=_BLOBFUSE2_SERVICE_NAME,
      )
      return base64.b64encode(cloud_init.encode()).decode()


  custom_data = storage_account.name.apply(  # ty: ignore[missing-argument, invalid-argument-type]
      _custom_data
  )
  ```
  (`pulumi.Output.all(...)` is no longer needed once there's only one `Output` to wait on.)
- Nothing else in the file changes — `virtual_machine`, `storage_blob_data_reader_role_assignment`, the monitor extension, and the DCR associations don't reference SQL.

### 3. `infra/templates/vm-cloud-init.yaml.j2` — drop the mssql extension and profile

Remove:
```yaml
  - sudo -u {{ admin_username }} -H code --install-extension ms-mssql.mssql --force
```
and the settings.json block that only ever carried the mssql profile:
```yaml
  - mkdir -p /home/{{ admin_username }}/.config/Code/User
  - echo '{{ vscode_settings_b64 }}' | base64 -d > /home/{{ admin_username }}/.config/Code/User/settings.json
```
Leave the `ms-azuretools.vscode-azurestorage` extension install line as-is — it's unrelated to the database, and untouched by this plan.

### 4. `infra/firewall.py` — remove the `AllowAzureSql` rule

Delete the whole `AllowAzureSql` `network.AzureFirewallApplicationRuleArgs` block (port 1433/MSSQL, `*.database.windows.net`) from `application_rule_collections`'s `workspaces-allow-restricted` collection. No other rule references it, and no renumbering is needed in the code itself (rules aren't numbered there) — only in `README-Firewall.md`'s prose numbering (see step 8).

### 5. `infra/__init__.py` — drop the re-exports

Remove the `from infra.database import (...)` block entirely, and drop `"admin_username"`, `"db_admin_password"`, `"sql_database"`, `"sql_firewall_rule"`, `"sql_server"` from `__all__`. (`admin_username` here was `infra.database`'s VM-*unrelated* admin username — `infra.compute` has its own separate, not-currently-re-exported `admin_username` for the VM; confirm nothing outside `infra.database`'s own module imports `admin_username` from the `infra` package top level before deleting it — the research for this plan found no such usage.)

### 6. `__main__.py` — drop the two stack outputs

Remove `db_admin_password` and `sql_server` from the `from infra import (...)` block, and delete:
```python
pulumi.export("sql_server_fqdn", sql_server.fully_qualified_domain_name)
pulumi.export("db_admin_password", pulumi.Output.secret(db_admin_password.result))
```

### 7. `Pulumi.dev.yaml` — drop the config

Remove the `rse-cloud-cybersecurity:db-admin-username: sqladmin` line.

### 8. Tests

- `git rm tests/test_database.py` — every test in it exercises a resource that no longer exists.
- `tests/test_compute.py` — delete `test_custom_data_pre_creates_the_mssql_connection_profile` in full (it decodes `custom_data` and asserts on the `mssql.connections` JSON block, which no longer exists).
- `tests/test_firewall.py` — in `test_application_rules_allow_this_vms_cloud_init_dependencies`, delete the one assertion referencing `AllowAzureSql`:
  ```python
  self.assertIn("*.database.windows.net", fqdns_by_rule_name["AllowAzureSql"])
  ```
  Leave the rest of that test (the other rules it checks) unchanged.
- `tests/conftest.py` needs no change — its `RandomPassword`/`RandomString` mock entries are generic and still needed for `vm_admin_password`; nothing in it is SQL-specific.
- Expect **69 tests** afterwards (74 today, minus 4 from `test_database.py` and 1 from `test_compute.py`; `test_firewall.py`'s test count is unchanged, only an assertion inside one test is removed).

### 9. Documentation

- **`infra/naming.py`**: revert the docstring's "storage accounts and SQL logical servers are both named in a global, not per-account, namespace" back to storage-account-only, e.g. *"Shared random suffix for the storage account's globally-unique name."* (`suffix` is still used by `infra/storage.py`; it's just no longer shared with anything else once `sql_server` is gone.)

- **`README.md`**:
  - Step 6 of "For users": remove the `db-admin-username`/`db_admin_password` clauses:
    ```markdown
    `vm-admin-username` is configurable (see `Pulumi.dev.yaml` for its default). The VM admin password is generated by Pulumi and exported as a secret stack output — retrieve it after deploying with `pulumi stack output vm_admin_password --show-secrets`.
    ```
  - "Project structure": update the `naming.py` bullet to drop "SQL logical server" (now just the storage account); delete the `database.py` bullet entirely; remove `test_database.py` from the `tests/` bullet's file list.
  - "Current scenario": the opening sentence names "an Azure SQL Database" as one of the three original components, and the closing paragraph discusses the database's still-public reachability as a deferred item — both need rewriting now that there's no database at all:
    ```markdown
    See [`specs/01-the-scenario.md`](specs/01-the-scenario.md) for the original design behind this infrastructure — a storage account, an Azure SQL Database, and a Linux VM able to reach both, all kept at minimum cost. The Azure SQL Database has since been removed from this branch entirely (see [`specs/remove-sql-database.md`](specs/remove-sql-database.md)) — the deployment is now just the storage account and the VM. Several of `specs/01-the-scenario.md`'s own planned security-hardening follow-ups have also been folded in: [...same Bastion/Log Analytics/Firewall/Storage-firewall/managed-identity bullets as today, unchanged...]

    RBAC for human/operator access to the resource group and SSH-key authentication on the VM remain deferred to a later iteration. See [`CLAUDE.md`](CLAUDE.md) for how changes to this infrastructure are verified (unit tests and static checks only — no live deployments).
    ```

- **`README-Firewall.md`**:
  - Intro/rationale paragraph: "the documented workflows in `README.md` reach the SQL Database and Storage Account over their public endpoints" → "reach the Storage Account over its public endpoint".
  - Delete rule item 7 (`Allow *.database.windows.net on port 1433 (MSSQL)`) and **renumber** items 8→7 (`AllowAzureStorage`) and 9→8 (`AllowAzureCli`).
  - Update every prose cross-reference to the renumbered rules: "Consolidation note (storage)"'s *"Rule 8 above no longer sees any real VM traffic... Rule 9 was added alongside it..."* → "Rule 7"/"Rule 8"; "Consolidation note (`az login`)"'s *"rule 9's four hosts"* → "rule 8's four hosts"; "Consolidation note (managed identity)"'s *"so rule 9 isn't actually needed for either"* and *"Rule 9 is kept as-is"* → "rule 8"/"Rule 8".
  - "One known gap" paragraph: drop the `ms-mssql.mssql` mention from the list of extensions the cloud-init script installs (only `ms-azuretools.vscode-azurestorage` remains).

- **`specs/02-managing-identity-storage.md`**: its "Out of scope (still deferred)" bullet explicitly forward-references *"removing the `0.0.0.0`–`255.255.255.255` SQL firewall rule... planned as a separate iteration"* — add a short note pointing at this document now that it's happened, matching this repo's existing pattern for cross-referencing a later plan from an earlier one (see `consolidating-managing-identities.md`'s own note in this same file).

## Out of scope for this document

- **Editing `specs/01-the-scenario.md` or any `specs/consolidating-*.md` file.** These are point-in-time design/consolidation records — they document why the database existed and how each prior change was merged at the time, not a living description of the current architecture. `README.md` is the living doc that gets updated; the historical specs are left as the historical record, consistent with how this repo already treats them.
- **Removing `infra/naming.py` or `infra.naming.suffix`.** Still needed by `infra/storage.py` for the storage account's name — only its docstring's SQL mention is stale.
- **Any change to the storage account, its firewall, its private endpoint, or the VM's managed identity/BlobFuse2 mount.** None of that depends on the database in any way.
- **Renaming or repurposing `db-admin-username`/`db_admin_password` for some other future use.** They're deleted outright, not kept around for a hypothetical future database.
- **Cost or design rationale for *why* the database is being removed.** Not this document's concern — it only covers *how* to remove it cleanly.
- **Claude running `pulumi preview`/`pulumi up`.** Per [CLAUDE.md](../CLAUDE.md), verification here is `ruff check`, `ruff format --check`, `ty check`, and `pytest` only; a human runs `pulumi preview`/`pulumi up` against a live stack to confirm the `sql_server`/`sql_database`/`sql_firewall_rule` resources are actually destroyed and nothing else is unexpectedly replaced.

## Verification checklist

- [ ] `infra/database.py` no longer exists.
- [ ] `uv run ruff check .` passes (in particular: no unused `json` import left in `infra/compute.py`, no unused `sql_server`/`sql_database`/`db_admin_password` imports anywhere).
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ty check` passes.
- [ ] `uv run pytest` passes with **69 tests** (down from 74): `tests/test_database.py` gone, `test_custom_data_pre_creates_the_mssql_connection_profile` gone, the `AllowAzureSql` assertion removed from `test_firewall.py`.
- [ ] `infra/compute.py`'s rendered `custom_data` contains no `mssql.connections` content and no `ms-mssql.mssql` extension install step.
- [ ] `infra/firewall.py`'s `application_rule_collections` contains no `AllowAzureSql` rule.
- [ ] `infra/__init__.py` and `__main__.py` reference nothing from `infra.database`.
- [ ] `Pulumi.dev.yaml` no longer has a `db-admin-username` key.
- [ ] `README.md`'s "Current scenario", "Project structure", and step-6 deploy instructions no longer mention the SQL Database, `db-admin-username`, or `db_admin_password`.
- [ ] `README-Firewall.md`'s rule list and every "Consolidation note" cross-reference use the renumbered rule numbers (7 = `AllowAzureStorage`, 8 = `AllowAzureCli`), and no longer mention `ms-mssql.mssql` or the SQL Database.
- [ ] `specs/02-managing-identity-storage.md` notes that the SQL firewall rule it flagged as future work has been removed, per this document.
- [ ] (Manual, by the user) `pulumi preview` shows `sql_server`, `sql_database`, and `sql_firewall_rule` being destroyed, the `AllowAzureSql` rule dropped from the firewall's application rule collection, `custom_data` changing (forcing the VM's `replace_on_changes=["osProfile.customData"]`), and nothing else replaced.
- [ ] (Manual, by the user) After `pulumi up`, the VM's VS Code has no `mssql` extension or pre-seeded connection profile, and the Application Firewall no longer allows `*.database.windows.net`.
