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

As explained above, the virtual machine can no longer use the VS Code Azure Storage extension once the Application Firewall is in place, since the extension's sign-in flow needs endpoints the firewall doesn't allow. Its own `virtual_network_rules` entry (see above) still lets it reach the storage account's data plane directly, though, so the Azure CLI works fine:

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

This is a natural fit for this repository: `az login` is already the only supported way to authenticate (see `CLAUDE.md`), so the VM doesn't need any new credentials or tooling, and `--auth-mode login` avoids having to generate or rotate a SAS token by hand.

The signed-in identity needs the **Storage Blob Data Contributor** role (or **Storage Blob Data Reader**, for download-only access) on the storage account or its resource group - the same role the main `README.md` already has you assign yourself for the Pulumi state container:

```sh
az role assignment create --role "Storage Blob Data Contributor" --assignee <email> \
  --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Storage/storageAccounts/<storage-account>
```

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

