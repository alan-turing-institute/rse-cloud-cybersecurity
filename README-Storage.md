# Storage Account

These changes demonstrate how access to the storage account can be controlled using Storage Account Firewall rules.

We also specify encryption requirements for securing the data at rest on the Azure servers.

## Details of implementation

The implementation here is quite straightforward.
In order to control access to the storage account we assign IP rules to the storage account itself.
These restrict to all IP addresses except the IP addresses or IP address ranges listed.

In order for this to work we must also create a "Microsoft.Storage" service endpoint, which we do by defining a new subnet and private endpoint for the storage account.

### Create a subnet and service endpoint

In order to use Azure Storage firewall rules and network access control we must create a "Microsoft.Storage" endpoint for the storage account.
This is done automatically when a rule is created using the portal, but since we're using Pulumi we must do this manually, as explained in the Azure documentation:

https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security

To do this we simply create a new subnet for the storage account with a given address range and specify the service endpoint as a parameter with the default options.
The implementation of this can be seen in the `infra/storage.py` file.

**Consolidation note:** this subnet's original address range (`10.0.5.0/24`) collided with the Application Firewall's management subnet (see `README-Firewall.md`), which is already deployed on that exact range. It's been moved to `10.0.6.0/24` - the two subnets would otherwise fail to deploy together.

See the documentation on azure virtual network service endpoints for more information:

https://learn.microsoft.com/en-us/azure/virtual-network/virtual-network-service-endpoints-overview

### Giving the virtual machine's own subnet a service endpoint too

The subnet above, on its own, doesn't give the virtual machine access to the storage account - nothing is deployed into it. Once the Application Firewall (`README-Firewall.md`) is in place, *all* of the VM's outbound traffic is forced through a `0.0.0.0/0` route to the firewall, so its requests to the storage account arrive from the firewall's own address, not from any address the storage account's firewall rules recognise. With `default_action` set to `Deny`, that traffic is refused, regardless of which tool makes the request.

Rather than adding an IP rule for the firewall's own (dynamically allocated) address, this consolidation instead gives the VM's own subnet (`vm_subnet`, in `infra/networking.py`) the same `Microsoft.Storage` service endpoint, and adds it as a second `virtual_network_rules` entry on the storage account (`infra/storage.py`). This is Microsoft's own documented fix for a subnet behind a forced-tunnelling route that also needs to reach a network-restricted PaaS service - see the [Azure API Management networking guidance](https://learn.microsoft.com/en-us/azure/api-management/api-management-using-with-vnet), which describes the identical interaction for a different Azure service.

**The trade-off:** enabling the service endpoint on `vm_subnet` makes its storage traffic use a more specific route than the firewall's `0.0.0.0/0` UDR, so that traffic goes to the storage account directly over the Azure backbone rather than via the Application Firewall. Two consequences follow:

- The Application Firewall's `AllowAzureStorage` application rule (see `README-Firewall.md`) no longer sees any real VM traffic once this ships. It's left in place as harmless defence in depth, in case the service endpoint is ever removed.
- **The VS Code Azure Storage extension no longer works from the virtual machine.** The storage account's own network rules are satisfied for the VM, but the extension's interactive sign-in and account-browsing depend on Microsoft Entra ID and Azure Resource Manager endpoints that were never added to the Application Firewall's allow-list, and this consolidation doesn't attempt to add them. See "Accessing the storage account from the virtual machine" below for the replacement workflow.

### Populating the "blob" private DNS zone - required, not optional

`infra/storage.py` also creates `storage_account_private_endpoint`, a Private Endpoint for the storage account's `blob` service (in `storage_subnet`). The moment *any* private endpoint exists for a storage account's blob service, Azure automatically rewrites that account's **public** DNS entry (`<account>.blob.core.windows.net`) into a CNAME pointing at `<account>.privatelink.blob.core.windows.net` - this isn't something we configure, it's an unconditional side effect of the private endpoint's existence.

Normally that's harmless: clients without any special DNS setup (e.g. anyone outside the VNet, like the Turing-VPN SAS workflow below) still resolve the `privatelink` name back to the account's public IP via Microsoft's own public CNAME chain, exactly as if the private endpoint didn't exist. But `infra/dns.py` (added for the Log Analytics private endpoint, well before this consolidation) already creates a `privatelink.blob.core.windows.net` private DNS zone - needed for an unrelated reason, Azure Monitor Private Link Scope's own blob-based ingestion - and links it to the **entire VNet**, not just the monitoring subnet. Once that zone exists and is linked, *any* DNS query for a name in it, from *anywhere* in the VNet (including the virtual machine, in `vm_subnet`), gets resolved against that zone instead of falling back to the public CNAME chain - and since nothing had ever added a record for our storage account to it, the lookup failed outright: `az storage blob upload`/`download` (and anything else on the VM resolving the storage account's name) got `Failed to resolve ... Name or service not known`, even with the storage account's own network rules and the Application Firewall both correctly configured.

**Fix:** `storage_account_private_dns_zone_group` links `storage_account_private_endpoint` to that same already-existing "blob" zone (`infra/dns.py`'s `dns_id["blob"]`) - the same `PrivateDnsZoneGroup` pattern `infra/dns.py` already uses for the Log Analytics endpoint. This populates the zone with the record it was missing, so `<account>.blob.core.windows.net` now resolves - from anywhere in the VNet - to the private endpoint's address in `storage_subnet`, rather than to nothing. One knock-on effect worth knowing: once this resolves privately, the VM's storage traffic goes over Private Link rather than the public endpoint at all, which means it now bypasses the storage account's `virtual_network_rules`/firewall (private endpoint traffic isn't subject to those) *and* the Application Firewall (it's VNet-internal traffic, not routed via the `0.0.0.0/0` UDR) - the `vm_subnet` service endpoint and `AllowAzureStorage` rule above are still correct to keep as defence in depth, but Private Link is now the access path that's actually exercised.

### Pass IP rules during creation

The IP rules specify which IP addresses are allowed access to the storage account resources.
We specify the addressed exposed by the Turing's VPN, meaning that only devices on the Turing network can access the storage account.
This could be adjusted to suit other corporate VPNs or requirements.

The IP addresses are provided as a list as can be seen in the `infra/storage.py` file.
The list is passed in as a parameter to the `storage.StorageAccount` initialiser.
Using this method the rules will be assigned when the storage account is created, but can also be adjusted later.

### Configure at-rest encryption

We also set the storage account to store data encrypted when at-rest.
This is done simply be specifying the `encryption` parameters when creating the Storage Account, as can also be seen in the `infra/storage.py` file.
See the following Azure documentation for more details:

https://learn.microsoft.com/en-us/azure/storage/common/storage-service-encryption

## References

1. Details about Azure Storage firewall rules:
   https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security
2. Guidelines and limitations of the Azure Storage firewall:
   https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security-limitations
3. Details about Azure virtual network service endpoints:
   https://learn.microsoft.com/en-us/azure/virtual-network/virtual-network-service-endpoints-overview
4. Details about Azure Storage encryption for data at rest:
   https://learn.microsoft.com/en-us/azure/storage/common/storage-service-encryption
5. Generate an SAS using Azure CLI:
   https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-cli

## Accessing the storage account from the virtual machine

As explained above, the virtual machine can no longer use the VS Code Azure Storage extension once the Application Firewall is in place, since the extension's sign-in flow needs endpoints the firewall doesn't allow. Its own `virtual_network_rules` entry (see above) still lets it reach the storage account's data plane directly, though.

The VM authenticates as **its own system-assigned managed identity** (`infra/compute.py`'s `virtual_machine`), which `infra/compute.py`'s `storage_blob_data_reader_role_assignment` grants **Storage Blob Data Reader** - **read-only**, and scoped to the `rse-demo-container` blob container specifically, not the whole storage account - as part of this Pulumi program, not a manual step. See [`specs/02-managing-identity-storage.md`](specs/02-managing-identity-storage.md) for the full design, including why the grant is read-only and container-scoped rather than broader.

### Reading the container: the BlobFuse2 mount (primary path)

`rse-demo-container` is mounted directly on the VM's own filesystem at `/mnt/rse-demo-container` via [BlobFuse2](https://github.com/Azure/azure-storage-fuse), authenticating with the managed identity (`mode: msi` in its config - see `infra/templates/blobfuse2-config.yaml.j2`). This is the primary, no-sign-in way to browse the container from the VM: open `/mnt/rse-demo-container` in VS Code, a terminal, or a file manager, exactly like any other local directory. The mount is read-only (`--read-only=true`, `infra/templates/blobfuse2.service.j2`), matching the identity's own read-only grant.

`mode: msi` reaches the VM's own Instance Metadata Service (`http://169.254.169.254`), the same endpoint `az login --identity` below uses - it's exempt from the Application Firewall's `0.0.0.0/0` route the same way the platform DNS server is, so **no Application Firewall rule is needed for the mount to authenticate**.

See [`specs/02-managing-identity-storage.md`](specs/02-managing-identity-storage.md#verifying-the-mount-manual) for the full manual verification procedure (confirming the service is active, the mount is browsable, and both the mount and the underlying RBAC grant actually refuse writes and cross-container reads).

### Accessing the container via the Azure CLI: read-only

The Azure CLI is also pre-installed on the virtual machine via cloud-init (see `infra/templates/vm-cloud-init.yaml.j2`), and can sign in as the same managed identity, with no browser, no device code, and no separate account to keep track of:

```sh
az login --identity
```

Like the mount, this goes through the VM's own IMDS endpoint, so it needs none of the `AllowAzureCli` firewall rule's endpoints (`login.microsoftonline.com` etc.) at all. That rule is still there and still useful - it's what makes plain `az login --use-device-code` work for a human operator signing in as *themselves* for other purposes - just not needed for this.

Get the storage account's name - **`pulumi` isn't installed on the VM, so run this on the machine you deployed the stack from, not the VM itself:**

```sh
pulumi stack output storage_account_name
```

The name is random-suffixed (see `infra/naming.py`), so the VM can't guess it - copy the value across (e.g. paste it over the RDP session) and set it on the VM:

```sh
STORAGE_ACCOUNT=<paste-the-value-from-above>

# Download a file from the demo container - this works: the identity has read access
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" --container-name "rse-demo-container" \
  --name <blob-name> --file <local-path> --auth-mode login
```

`--auth-mode login` uses whichever identity is currently signed in - the managed identity here - rather than fetching an account key, so this needs no SAS token or a key.

**Uploading from the VM no longer works.** `az storage blob upload --auth-mode login` fails with an authorization error (`AuthorizationPermissionMismatch`/`403`) - the identity's grant is Storage Blob Data **Reader**, not Contributor, and that's deliberate: see [`specs/02-managing-identity-storage.md`](specs/02-managing-identity-storage.md) and [`specs/consolidating-managing-identities.md`](specs/consolidating-managing-identities.md) for why least-privilege, read-only access for the VM's own identity took priority over keeping this write path alive. If you need to add data to the container, do it from a device on the Turing VPN via the SAS workflow below (or via the retained account key/Portal), not from the VM.

If the download above fails with `You do not have the required permissions to perform this operation`, check:

- **The role assignment hasn't propagated yet.** Azure RBAC changes can take several minutes to take effect after a fresh `pulumi up`; retry after a short wait.
- **`az login --identity` actually succeeded and picked up the VM's identity**, not a stale cached login as some other account - `az account show --query user -o json` should show `"type": "servicePrincipal"`.
- **You're looking at the right role assignment.** Confirm it exists with:
  ```sh
  az role assignment list --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Storage/storageAccounts/<storage-account>/blobServices/default/containers/rse-demo-container -o table
  ```
  It should show `Storage Blob Data Reader` assigned to a principal of type `ServicePrincipal` - that's the VM's managed identity, not a user.

## Creating a Blob Storage SAS URL

With this configuration we can now upload data to or download data from the storage account from a device using one of the authorised IP addresses. This is a separate path for a human on the Turing VPN (e.g. via Microsoft Storage Explorer), unaffected by the virtual machine's own access above.

In order to do this we can generate an SAS URL that can be used with Microsoft Storage Explorer.
Your user will need to have the "Storage Blob Data Contributor" in order to generate suitable tokens and you'll need to have the Azure CLI installed.

You can also generate tokens directly from Azure portal.

Before generating a token we'll want to store the generated storage account name into an environment variable.
This will make the later commands easier to run.

```sh
STORAGE_ACCOUNT=$(pulumi stack output storage_account_name)
```

Next we run a couple of commands to generate an SAS token URL.
The Azure CLI will generate tokens, but not full URLs, so we need to turn it in to a suitable URL ourselves.

To generate a token with list and write access permissions, suitable for uploading data to the storage account, you can run the following:

```sh
$ SAS_TOKEN=$(az storage container generate-sas \
    --account-name $STORAGE_ACCOUNT --name "rse-demo-container" \
    --permissions lw --https-only --auth-mode key -o tsv \
    --expiry $(date -d "tomorrow" "+%Y-%m-%dT%H:%MZ") \
    2>/dev/null)
$ echo "https://$STORAGE_ACCOUNT.blob.core.windows.net/rse-demo-container?$SAS_TOKEN"
```

To generate a token with list and read access permissions, suitable for downloading data from the storage account, you can run the following:

```sh
$ SAS_TOKEN=$(az storage container generate-sas \
    --account-name $STORAGE_ACCOUNT --name "rse-demo-container" \
    --permissions lr --https-only --auth-mode key -o tsv \
    --expiry $(date -d "tomorrow" "+%Y-%m-%dT%H:%MZ") \
    2>/dev/null)
$ echo "https://$STORAGE_ACCOUNT.blob.core.windows.net/rse-demo-container?$SAS_TOKEN"
```

These SAS URLs can then be pasted into Microsoft Storage Explorer to upload and download data to and from the storage account.
To do this, start up Storage Explorer, then select the "Open Connect Dialog" button on the left hand side (it looks like a plug).
Select the "Blob container or directory" option in the dialog box that opens.
Select "Shared access signature URL (SAS)" from the options and select "Next".
Past the full SAS URL into the lower box with the caption "Blob container or directory SAS URL".
The "Display name" field should get populated automatically.

You can now select "Next" to see a summary of your options.
Select "Connect" to connect to the Storage Account container blob.

Depending on the permissions granted by the SAS URL, you will now be able to upload data to or download data from the container blob storage.

For more details about generating SAS tokens using the Azure CLI, see the following Azure documentation:

https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-cli

