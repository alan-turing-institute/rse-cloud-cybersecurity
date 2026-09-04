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

See the documentation on azure virtual network service endpoints for more information:

https://learn.microsoft.com/en-us/azure/virtual-network/virtual-network-service-endpoints-overview

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

## Creating a Blob Storage SAS URL

With this configuration we can now upload data to or download data from the storage account from a device using one of the authorised IP addresses.

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

