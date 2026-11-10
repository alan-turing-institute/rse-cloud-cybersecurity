"""Storage account, reachable over the public internet at this stage."""

from typing import Any

import pulumi
from pulumi_azure_native import storage
from pulumi import Input, Output, ResourceOptions

from infra.naming import suffix
from infra.resource_group import resource_group

from azure.storage.fileshare import ShareDirectoryClient, ShareFileClient

# Used by create() to either open or create an appropriate ShareFileClient
def get_file_client(
    storage_account_name: str,
    storage_account_key: str,
    share_name: str,
    destination_path: str,
) -> ShareFileClient:
    tokens = destination_path.split("/")
    directory = "/".join(tokens[:-1])
    file_name = tokens[-1]
    # See: https://learn.microsoft.com/en-us/python/api/azure-storage-file-share/azure.storage.fileshare.aio.sharedirectoryclient?view=azure-python
    if directory:
        # Check if the full path exists; no need to create directories if it does
        directory_client = ShareDirectoryClient(
            account_url=f"https://{storage_account_name}.file.core.windows.net",
            share_name=share_name,
            directory_path=directory,
            credential=storage_account_key,
        )
        if not directory_client.exists():
            # If it doesn't exist we need to walk the path starting from the root
            directory_client = ShareDirectoryClient(
                account_url=f"https://{storage_account_name}.file.core.windows.net",
                share_name=share_name,
                directory_path="",
                credential=storage_account_key,
            )
            for subdir in tokens[:-1]:
                # Move to the subdirectory, which need not yet exist
                directory_client = directory_client.get_subdirectory_client(subdir)
                if not directory_client.exists():
                    # Create the subdirectory if it doesn't already exist
                    directory_client.create_directory()
        return directory_client.get_file_client(file_name)

    return ShareFileClient(
        account_url=f"https://{storage_account_name}.file.core.windows.net",
        share_name=share_name,
        file_path=file_name,
        credential=storage_account_key,
    )

# Create a file with specified content in the storage account file share
# This mirrors the code in file_share_file.py
def create(props: dict[str, Any]) -> None:
    """Create file in target storage account with specified contents."""
    outs = dict(**props)
    file_client: ShareFileClient | None = None
    try:
        file_client = get_file_client(
            props["storage_account_name"],
            props["storage_account_key"],
            props["share_name"],
            props["destination_path"],
        )
        file_client.upload_file(props["file_contents"].encode("utf-8"))
        outs["file_name"] = file_client.file_name
    except Exception as exc:
        file_name = file_client.file_name if file_client else ""
        msg = f"Failed to upload data to '{file_name}' in [green]{props['share_name']}[/]."
        raise Exception(msg) from exc
    print(f"filesharefile-{props['destination_path'].replace('/', '-')}")
    print(f"Outs: {outs}")


# Create the Storage Account
storage_account = storage.StorageAccount(
    "subdir-storage-account",
    resource_group_name=resource_group.name,
    account_name=pulumi.Output.concat("subdir", suffix.result),
    kind=storage.Kind.STORAGE_V2,
    sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS),
)

# Extract the keys for storing content in the file share
storage_account_keys = storage.list_storage_account_keys_output(
    account_name=storage_account.name,
    resource_group_name=resource_group.name,
)

storage_account_key = storage_account_keys.keys[0].value

# Create a blog container (which we're not actually using)
blob_container = storage.BlobContainer(
    "subdir-demo-container",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
)

# Create a file share to store directories and a file in
file_share = storage.FileShare(
    f"subdirtest_file_share_01",
    access_tier=storage.ShareAccessTier.TRANSACTION_OPTIMIZED,
    account_name=storage_account.name,
    resource_group_name=resource_group.name,
    share_name="subdir-test-share",
    share_quota=1,
    signed_identifiers=[],
)

# Upload file
file_content = '<configuration><root level="info"/></configuration>'

# Preliminary properties dictionary to be populated incrementally
props = {
    "storage_account_name": None,
    "storage_account_key": None,
    "share_name": None,
    "destination_path": "etc/logback/logback-overrides.xml",
    "file_contents": file_content,
}

# Chain together the property collection using lambdas
def get_sa_name_value(x):
    global props
    props["storage_account_name"] = x
    storage_account_key.apply(lambda v: get_sa_key_value(v))

def get_sa_key_value(x):
    global props
    props["storage_account_key"] = x
    file_share.name.apply(lambda v: get_fs_name_value(v))

def get_fs_name_value(x):
    global props
    props["share_name"] = x
    create(props)

storage_account.name.apply(lambda v: get_sa_name_value(v))
