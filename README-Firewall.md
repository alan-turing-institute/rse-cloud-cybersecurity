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

The changes to create the subnets and IP addresses can be found in the `infra/firewall.py` file.

### Define Firewall NAT rule

Since any traffic attempting to access the public IP address of the virtual machine will now be blocked, in order to SSH into the virtual machine we must now go via the Firewall.
In a full set up we would use the Bastion host for this (see the separate section on Bastion hosts).
However, to keep things simple we're going to create a NAT rule to allow SSH access to be forwarded from the firewall directly on to the virtual machine.

We can see the code for this defined by `nat_rule_collections` in the `infra/firewall.py` file.

As configured the rule passes any connections to the firewall on port 22 on to the virtual machine, as long as the source address is 193.60.220.253.
This address is the IP address that users of the Turing's VPN are exposed on.
It could be switched for a different IP to support a different corporate VPN configuration.

### Define Firewall application rules

We define one Deny rule and several Allow rules, one collection each.
Almost all outgoing connections will be blocked.
The original allow rules from this PR are:

1. Allow access to `keyserver.ubuntu.com` on port 11371 (HKP/OpenPGP).
2. Allow access to `api.snapcraft.io` on port 443 (HTTPS).
3. Allow access to `download1.rstudio.org` on port 443 (HTTPS).

These allow snap and R packages to be downloaded to the virtual machine.
In a more secure setup, these would be directed to package mirrors hosted inside the Azure environment.

**These three rules alone are not enough for this repository's own VM.** Its `infra/templates/vm-cloud-init.yaml.j2` installs packages from Ubuntu's own archives and from the VS Code/Chrome apt repos, and the documented workflows in `README.md` reach the SQL Database and Storage Account over their public endpoints - none of which the three rules above cover. Consolidating this PR added the following rules to the same allow collection so the VM keeps working once its subnet's traffic is routed through the firewall:

4. Allow `archive.ubuntu.com`, `azure.archive.ubuntu.com`, `security.ubuntu.com`, `changelogs.ubuntu.com` on port 80 (HTTP) - the Ubuntu package archives `apt-get` needs.
5. Allow `packages.microsoft.com` on port 443 (HTTPS) - the VS Code apt repo, and (same host, a different path) the Azure CLI apt repo.
6. Allow `dl.google.com` on port 443 (HTTPS) - the Google Chrome apt repo.
7. Allow `*.database.windows.net` on port 1433 (MSSQL) - the Azure SQL Database public endpoint.
8. Allow `*.blob.core.windows.net` on port 443 (HTTPS) - the Storage Account public endpoint.
9. Allow `login.microsoftonline.com`, `login.windows.net`, `*.login.microsoft.com`, and `management.azure.com` on port 443 (HTTPS) - Microsoft Entra ID's token endpoints and Azure Resource Manager, needed for `az login --use-device-code` and for the Azure CLI generally when signed in as a *user* (see `README-Storage.md`'s "Accessing the storage account from the virtual machine").

**Consolidation note (storage):** once `05-storage` lands (see `README-Storage.md`), the virtual machine's own subnet gets a `Microsoft.Storage` service endpoint, so its storage traffic takes a more specific route than this firewall's `0.0.0.0/0` UDR and reaches the Storage Account directly over the Azure backbone. Rule 8 above no longer sees any real VM traffic as a result - it's left in place as harmless defence in depth, in case the service endpoint is ever removed. Rule 9 was added alongside it once it turned out the Azure CLI wasn't installed on the VM at all - it's now installed via cloud-init (see `infra/templates/vm-cloud-init.yaml.j2` and `README-Storage.md`'s "Accessing the storage account from the virtual machine").

**Consolidation note (`az login`):** rule 9's four hosts are deliberately just the token-protocol endpoints, not the Microsoft sign-in *page's* CDN assets (e.g. `aadcdn.msftauth.net`) - those aren't a small, fixed set worth chasing, same reasoning as the VS Code Marketplace gap below. `az login --use-device-code` never needs the sign-in page to render on the VM at all (the human completes it on a separate device), so it works with just these four hosts; plain `az login` doesn't, and isn't supported here - see `README-Storage.md`.

**Consolidation note (managed identity):** the VM's actual storage access (see `README-Storage.md`) ended up using `az login --identity` and the VM's own system-assigned managed identity instead, granted `Storage Blob Data Contributor` directly by this Pulumi program (`infra/storage.py`'s `vm_storage_blob_data_contributor`) rather than by a manual role assignment for a human's account. `az login --identity` goes through the VM's Instance Metadata Service (`169.254.169.254`), which - like the platform DNS server - is exempt from the `0.0.0.0/0` route and reachable regardless of this firewall, so rule 9 isn't actually needed for that path. It's kept as-is because `az login --use-device-code` (signing in as a human, for anything other than the storage workflow) is still a legitimate, supported thing to do on this VM.

One known gap: the VS Code Marketplace extension installs the cloud-init script also runs (`ms-mssql.mssql`, `ms-azuretools.vscode-azurestorage`) reach additional Microsoft CDN endpoints not enumerated here (e.g. `marketplace.visualstudio.com`, `*.gallerycdn.vsassets.io`) - these weren't added because that endpoint set isn't officially pinned down and can change; if `pulumi up` shows cloud-init failing on the extension install steps specifically, check the VM's `/var/log/cloud-init-output.log` for the blocked host and add it here.

We also define one Deny rule:

1. Deny access to `dashboard.snapcraft.io`, `login.ubuntu.com` and `upload.apps.ubuntu.com` on ports 80 (HTTP) and (HTTPS).

This is to prevent snap package uploads, which might otherwise provide a way to egress data from the system.

The rules are defined in the `infra/firewall.py` file.

### Deploy the Firewall

The code to define the firewall can also be found in `infra/firewall.py`.
We pass the firewall and management public IP addresses as parameters, alongside the NAT and application rules we defined earlier.

Although the code to define it is straightforward, it typically takes a long time for Azure to deploy a firewall (some tens of minutes).

### Route traffic

Finally we create a routing table in the `infra/networking.py` file and a route in the `infra/firewall.py` to ensure that all traffic is routed via the firewall.

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

The VM has no public IP of its own (see `README-Bastion.md`) - the general-purpose way in is the Bastion host. This firewall's NAT rule adds a second, narrower path: SSH forwarded from the firewall's own public IP straight to the VM, for the single source IP address configured below. Use whichever suits the demo; the two don't conflict, since they front different public IPs.

Connecting via this NAT rule must be done using the firewall's public IP address, rather than the address of the virtual machine.

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

