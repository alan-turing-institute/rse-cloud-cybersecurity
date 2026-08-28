# Azure Bastion Host

These changes demonstrate how to deploy an Azure Bastion Host to act as an intermediary for connecting to a Virtual Machine using either SSH or RDP.

## Details of implementation

The basic deployment includes a virtual machine with a public IP address that can be accessed directly.
This exposes the machine to the wider Internet, which is a security risk.

To avoid this, we're going to protect the virtual machine using a bastion host.
This is a hardened machine that's used as an external gateway to other resources.
In our case, we'll allow connections to the virtual machine via the bastion host, but no other access will be allowed.

A bastion host can also be helpful if you have more than one virtual machine, since it can allow connectivity to all of the virtual machines through a single interface.

There are essentially three changes needed to support a bastion host:

### Remove the public IP address from the virtual machine

Once the virtual machine is accessed through the bastion host it'll no longer need a public IP address.
Indeed, keeping the public IP address would be a security vulnerability, compromising the benefit of having the bastion host in the first place.

To remove it we simply drop the `public_ip` resource and remove the reference to it from the `network_interface` resource.

To see the full details check the changes to the `infa/networking.py` file.

### Add a subnet for the bastion host

We create a new file `infra/bastion_network.py` that defines subnet for the bastion host.
The resource that creates this is called `bastion_subnet` and is configured to use the `virtual_network` virtual network created in `infra/networking.py`.
We must use a separate address space within the virtual network from the virtual machine.

In order to allow access the bastion host from the Internet we also need to create a public IP address.
The resource for this is called `bastion_public_ip`.
Inspecting the constructor arguments shows the properties of the IP address: a standard static IP address.

We also need a network security group with appropriate rules.
Quite a few rules are needed in order for the bastion host to work effectively and creation will fail if they're not set up properly.
The Microsoft documentation [provides full details](https://learn.microsoft.com/en-us/azure/bastion/bastion-nsg#nsg) of the rules needed.

### Create the bastion host

The bastion host itself is created as a resource in the `infra/bastion.py` file.
With all of the other pieces set up, defining the bastion host is straightforward.

We set `enable_shareable_link` to be true, so that we can generate links that can be passed to others for access to the virtual machine.
This gives access to the bastion host, but credentials are still needed for access to the virtual machine.

We set `enable_tunneling` to be true since this allows users to connect to the virtual machine using SSH via the Azure CLI, which can be convenient.
In the Azure Portal and Azure documentation this feature is referred to as "Native client support".

The SKU must also be set to "Standard" in order to allow these features to work.

### Update the unit tests

The original unit tests in `tests/test_networking.py` performed a test to ensure the virtual machine is configured with a public IP address.
With a bastion host this is no longer the case.
The unit tests must therefore be updated.
We've changed the test to do the opposite: it now checks that the virtual machine *doesn't* have a public IP address.

### Expose the configuration

In the original `__main__.py` file the public IP address of the virtual machine was exported so that it could be used to access the machine.
Since it no longer has a public IP address we've removed it from here.
Instead we're exporting the public IP address of the bastion host.

For convenience we also export the bastion host ID and virtual machine ID, since this allows us to make SSH and RDP connections to it using the Azure CLI more easily.

## References

1. Details of how to configure and connect to a virtual machine via a Bastion Host:
   https://learn.microsoft.com/en-us/azure/bastion/bastion-connect-vm-ssh-linux?tabs=entra-id%2Cnative-client
2. Details for how to configure a Bastion Host for native client connections can be found here:
   https://learn.microsoft.com/en-gb/azure/bastion/native-client
3. Details of the Network Security Group rules needed for a Bastion Host:
   https://learn.microsoft.com/en-us/azure/bastion/bastion-nsg

## Connecting to the Virtual Machine

You can connect to the virtual machine via the Bastion Host.

To make your life easier, set `PULUMI_CONFIG_PASSPHRASE` to your Pulumi password and export it to avoid having to enter your Pulumi password on every command.

```sh
$ read -s PULUMI_CONFIG_PASSPHRASE
<type-your-password>
$ export PULUMI_CONFIG_PASSPHRASE
```

For a complete system the virtual machine would be configured to use Entra ID, but we're using the username and password of the virtual machine for the sake of demonstration.

The virtual machine username is configured as `azureuser`.

To get the password for access to the virtual machine use the following command:

```sh
$ pulumi stack output vm_admin_password --show-secrets
```

Assuming you cached your Pulumi password earlier the virtual machine admin password will be output to the console.

We'll also need the Resource ID of the Bastion Host and the virtual machine we want to connect to.These are long and confusing strings, so we'll capture them in a couple of environment variables to avoid having to copy and paste them everywhere.

```sh
$ BASTION_ID=$(pulumi stack output bastion_id)
$ VM_ID=$(pulumi stack output vm_id)
```

We can now access the virtual machine through the Azure CLI using tunneling.
To do this you'll need the `bastion` and `ssh` extensions installed:

```sh
$ az extension add -n bastion
$ az extension add -n ssh
```

You can then log in and get a console on the virtual machine using the following command:

```sh
$ az network bastion ssh --ids $BASTION_ID --target-resource-id $VM_ID \
    --auth-type password --username azureuser
```

You'll be asked to enter a password to log in; you can use the password obtained above.

## Creating a shareable link

You can also create a shareable link to the Bastion Host that can be passed to others.
They'll still need a username and password for the virtual machine, but this allows them to access it without having access to the Azure Portal or needing to have the Azure CLI tools installed.

Assuming the `BASTION_ID` and `VM_ID` environment variables are still set from the previous section, create a shareable link with the following command:

```sh
$ az rest --method POST \
    --url "${BASTION_ID}/createShareableLinks?api-version=2025-05-01" \
    --body $(jq -cn --arg id $VM_ID '{vms:[{vm: $ARGS.named}]}') \
    | jq -r '.value[0].bsl'
```

This creates the link asynchronously, so it won't necessarily be output.
It takes only a second or two to create the link, so after a brief pause you can access it using the following command:

```sh
$ az rest --method POST \
    --url "${BASTION_ID}/getShareableLinks?api-version=2025-05-01" \
    --body $(jq -cn --arg id $VM_ID '{vms:[{vm: $ARGS.named}]}') \
    | jq -r '.value[0].bsl'
```

This will output a link to the console.
To use the link, activate it or copy it to your browser and a page will open providing options for how to connect.
Select SSH for console access or RDP for desktop access.
You'll need to enter the `azureuser` username and password from earlier.
