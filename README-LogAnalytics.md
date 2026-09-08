# Azure Log Analytics Workspace

These changes demonstrate how to deploy an Azure Log Analytics Workspace to the architecture.

This will allow collecting of logs and performance data from the Virtual Machine and can be extended to collect data from other components as well.

## Details of implementation

The basic deployment includes a virtual machine running Linux.
By default logs are collected on the virtual machine itself.
By providing a log analytics endpoint and rules, the system logs will be transferred to the Log Analytics workspace.

There are essentially four changes needed to support a bastion host:

### Create a Log Analytics Workspace

The Log Analytics Workspace is defined in the new `infra/monitoring.py` file.
Configuring the workspace is straightforward: we just have to specify the length of time to retain the logs for and the SKU to use.

### Create a Data Collection Endpoint

The Data Collection Endpoint defines where data can be sent to for ingestion by the log analytics workspace.
The implementation for our Data Collection Endpoint can also be found in the `infra/monitoring.py` file.
For more information about data collection endpoints, see the following Azure documentation:

https://learn.microsoft.com/en-us/azure/azure-monitor/data-collection/data-collection-endpoint-overview

We disable public network access to the Data Collection Endpoint to increase security.
However, because of this we have to do some extra work setting up a subnet, private link scope and DNS zone, as detailed later.

### Create Data Collection Rules

Data Collection Rules are used to specify what sort of data to collect from your Azure components.
The implementation for our Data Collection Rules can also be found in the `infra/monitoring.py` file.

We must define where the data will go (in our case the Log Analytics Workspace), dataflows to specify where the data will come from as well as specific data sources.
We've chosen data sources relevant to the Virtual Machine deployment of our example.

Collection rules can be quite specific.
For example, if you're running a Linux host the specific services and debug levels that will be collected can be specified.

For more information about Data Collection Rules, see the following Azure documentation:

https://learn.microsoft.com/en-us/azure/azure-monitor/data-collection/data-collection-rule-overview

### Create a Private Link Scope

Because we've disabled public access to the Data Collection Endpoint we must set up a private link scope to use with it.
We do this in the `infra/monitoring.py` file alongside the endpoint.
We must link both the Log Analytics Workspace and the Data Collection Endpoint to the link scope in order to allow communication to succeed, which we do with by creating two `monitor.PrivateLinkScopedResource` resources.

### Create a Private Subnet and Network Endpoint

We've already created a Data Collection Endpoint, but we must also create a Private Network Endpoint in its own subnet for the private link scope.
We do this in the `infra/monitoring.py` file.

### Configure DNS

Without DNS the monitoring extension won't be able to connect to the `network.PrivateEndpoint`.
We'll use the standard Azure DNS servers, but still need to configure the appropriate DNS zones.

This is done in the `infra/dns.py` file.
There we create five zones for each of the following domains:

1. `privatelink.monitor.azure.com`
2. `privatelink.oms.opinsights.azure.com`
3. `privatelink.ods.opinsights.azure.com`
4. `privatelink.agentsvc.azure-automation.net`
5. `privatelink.blob.core.windows.net`

These zones have been taken from the Azure documentation:

https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/private-link-configure?review-and-validate-ampls-configuration

For each zone we create the Private Zone, create a Virtual Network Link for each associated with the virtual network and finally create a Private DNS Zone Group that covers all of the private zones.

### Configure the Virtual Machine

The changes needed to ensure the Virtual Machine sends logging data to our Log Analytics Workspace can be found in the `infra/compute.py` file.
Here we add the Azure Monitoring extension to the virtual machine to give it the functionality required.

We also set up associations for the data collection endpoint and rules that we created in the `infra/monitoring.py` file.

### Configure Monitoring Alerts

We can use the performance data collected from the guest operating system of the virtual machine to trigger alerts.
We've created two alerts: one will trigger if average CPU utilisation exceeds 90% over a five minute period; the other will trigger if average memory utilisation exceeds 75% over a five minute period.
When triggered the alerts will trigger an action to send an email to a specific email address provided.

The implementation is provided in the `infra/alerts.py` file.
At the top of the file is a variable `email_address` which is currently set to an example email address.
You should change this to be your own email address to receive the alerts.

For an overview of alerts, see the following Azure documentation:

https://docs.azure.cn/en-us/azure-monitor/alerts/alerts-overview

There are two steps to creating an alert: first create the action, then create an alert that uses the action.
For the action group we create a `monitor.ActionGroup` resource, providing details of the email recipient for the alert and setting it as enabled.

For further details about Action Groups, see the following Azure documentation:

https://docs.azure.cn/en-us/azure-monitor/alerts/action-groups

We then set up our alerts.
They've both very similar.
Each must include the criteria for the alert, the window size to collect data over, the frequency of checking, the severity level of the alert and the action to perform.
We also set the alert to be enabled.
For more information about creating metric alert rules, see the following Azure documentation:

https://docs.azure.cn/en-us/azure-monitor/alerts/alerts-create-metric-alert-rule

## References

1. Details of how to configure and create a Log Analytics Workspace:
   https://docs.azure.cn/en-us/azure-monitor/logs/quick-create-workspace
2. Details about Data Collection Endpoints:
   https://learn.microsoft.com/en-us/azure/azure-monitor/data-collection/data-collection-endpoint-overview
3. Details about Data Collection Rules:
   https://learn.microsoft.com/en-us/azure/azure-monitor/data-collection/data-collection-rule-overview
4. Details about how to configure a private link for the Monitor:
   https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/private-link-configure
5. Details about Action Groups for setting up alerts:
   https://docs.azure.cn/en-us/azure-monitor/alerts/action-groups
6. Alerts overview:
   https://docs.azure.cn/en-us/azure-monitor/alerts/alerts-overview
7. Creating metrics-based alerts:
   https://docs.azure.cn/en-us/azure-monitor/alerts/alerts-create-metric-alert-rule

## Viewing Logs

Logs will now be collected in the Log Analytics Workspace which can be accessed through the Azure Portal.
Navigate to the relevant subscription, select the appropriate resource group, in our case `rse-cloud-sybesecurity-rg`.
There you'll see a Log Analytics workspace component.
In our case this is called `rse-log-analytics`.

Now we can, for example, create a query to view the system logs: select the "Logs" option in the menu on the left.
Select the "Queries" icon, open out the "Virtual Machines" entry in the list and select "All Syslog".
This will create a query to show recent logs in the main pane.
