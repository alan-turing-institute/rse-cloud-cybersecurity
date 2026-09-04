# Azure Firewall

These changes demonstrate how to add an Azure Firewall to the deployment to support restrictions application-level site and service access from inside the virtual machine as well as IP-restricted access of incoming connections to the virtual machine.

## Details of implementation

The basic deployment includes the firewall and several firewall rules.
In order to support the firewall two new public IP addresses are needed: one for the firewall and one for firewall management.
The latter is a requirement of the Azure Standard firewall SKU in order for Microsoft to apply updates and collect measurement data.

We deploy one NAT rule to support restricted incoming access to the virtual machine.

We deploy a further four application rules (three allow and one deny) to support restricted access to certain external sites.
All other outgoing Internet access is blocked.

A routing table is also added to ensure traffic is routed through the firewall.

### Create Subnets and IP addresses

We create a new subnet in our Virtual Network address space for the Firewall.
We also create two new public IP addresses.
The first is for access to the Firewall itself; the second is to expose the Firewall Management.
Firewall management traffic is separated from Firewall traffic using a separate NIC, see the following page for more details:

https://learn.microsoft.com/en-us/azure/firewall/management-nic

The changes to create the subnets and IP addresses can be found in the `infra/firewally.py` file.

### Define Firewall NAT rule

Since any traffic attempting to access the public IP address of the virtual machine will now be blocked, in order to SSH into the virtual machine we must now go via the Firewall.
In a full set up we would use the Bastion host for this (see the separate section on Bastion hosts).
However, to keep things simple we're going to create a NAT rule to allow SSH access to be forwarded from the firewall directly on to the virtual machine.

We can see the code for this defined by `nat_rule_collections` in the `infra/firewall.py` file.

As configured the rule passes any connections to the firewall on port 22 on to the virtual machine, as long as the source address is 193.60.220.253.
This address is the IP address that users of the Turing's VPN are exposed on.
It could be switched for a different IP to support a different corporate VPN configuration.

### Define Firewall application rules

We define three Allow rules and one Deny rule.
Almost all outgoing connections will be blocked.
The allow rules are the following:

1. Allow access to `keyserver.ubuntu.com` on port 11371 (HKP/OpenPGP).
2. Allow access to `api.snapcraft.io` on port 443 (HTTPS).
3. Allow access to `download1.rstudio.org` on port 443 (HTTPS).

These allow snap and R packages to be downloaded to the virtual machine.
In a more secure setup, these would be directed to package mirrors hosted inside the Azure environment.

We also define one Deny rule:

1. Deny access to `dashboard.snapcraft.io`, `login.ubuntu.com` and `upload.apps.ubuntu.com` on ports 80 (HTTP) and (HTTPS).

This is to prevent snap package uploads, which might otherwise provide a way to egress data from the system.

The rules are defined in the `infra/firewall.py` file.

### Deploy the Firewall

The code to define the firewall can also be found in `infra/firewall.py`.
We pass the firewall and management public IP addresses as parameters, alongside the NAT and application rules we defined earlier.

Although the code to define it is straightforward, it typically takes a long time for Azure to deploy a firewall (some tens of minutes).

### Route traffic

Finally we create a routing table in the `infra/networking.py` file and a route in the `infra/firewally.py` to ensure that all traffic is routed via the firewall.

We use the system default route "0.0.0.0/0" as this will be overruled by anything more specific, such as VNet to VNet traffic which we do not want to send via the firewall.
See the following page in the Azure documentation for more details:

https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview

## References

1. Deploy a firewall using the Azure portal:
   https://learn.microsoft.com/en-us/azure/firewall/tutorial-firewall-deploy-portal
2. Configuring Azure Firewall rules:
   https://learn.microsoft.com/en-us/azure/firewall/rule-processing
3. Details about the Azure Firewall Management NIC:
   https://learn.microsoft.com/en-us/azure/firewall/management-nic
4. Info about virtual network traffic routing:
   https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview

## Connecting to the Virtual Machine

Once the firewall is running, connecting to the virtual machine must be done using the firewall's public IP address, rather than the address of the virtual machine.

If you specified a source address for the NAT rule you must also connect from the correct IP address as well (e.g. using a VPN).

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

Now we can get the firewall IP address and use it to SSH into the virtual machine:

```sh
$ FIREWALL_IP=$(pulumi stack output firewall_public_ip)
$ ssh azureuser@$FIREWALL_IP
```

You'll be asked to enter a password to log in; you can use the password obtained above.

