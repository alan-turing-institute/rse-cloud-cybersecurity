# rse-cloud-cybersecurity

A repository for the "Cloud Cybersecurity for Research Engineers​" presentation at RSECON26.

This repository contains a [Pulumi](https://www.pulumi.com/) program, written in Python, that deploys Azure infrastructure. See [`specs/tech-stack.md`](specs/tech-stack.md) for the full technology stack.

## Prerequisites

- [Python](https://www.python.org/) 3.11 or later
- [uv](https://docs.astral.sh/uv/) for Python environment and dependency management
- [Pulumi CLI](https://www.pulumi.com/docs/iac/download-install/)
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`), authenticated via `az login` — this is the only supported way to authenticate against Azure
- An Azure Blob Storage container for the Pulumi state backend (see step 3 below if you don't have one yet)

## For users: running the deployment

1. Clone the repository and move into it:

   ```bash
   git clone https://github.com/<org>/rse-cloud-cybersecurity.git
   cd rse-cloud-cybersecurity
   ```

2. Log in to Azure:

   ```bash
   az login
   ```

3. Provision (or reuse) a storage account and blob container to hold the Pulumi state, if one doesn't already exist:

   ```bash
   az storage account create --name <storage-account> --resource-group <resource-group>
   az storage container create --name <container> --account-name <storage-account> --auth-mode login
   ```

   See [Create an Azure storage account](https://learn.microsoft.com/en-us/azure/storage/common/storage-account-create) and [Manage blob containers using Azure CLI](https://learn.microsoft.com/en-us/azure/storage/blobs/blob-containers-cli) for the full set of options (redundancy, access tier, networking, etc.).

   Since this project authenticates solely via the Azure CLI, grant your account the **Storage Blob Data Contributor** role on the storage account (or its resource group) so Pulumi can read/write state — see [Assign an Azure role for access to blob data](https://learn.microsoft.com/en-us/azure/storage/blobs/assign-azure-role-data-access).

4. Log Pulumi in to the Azure Blob Storage state backend, using the container name from step 3 and the storage account it lives in:

   ```bash
   pulumi login "azblob://<container>?storage_account=<storage-account>"
   ```

   The `<container>` value is just the container name you chose above (e.g. `pulumi-state`); `<storage-account>` is the account it was created in. See Pulumi's [Azure Blob Storage backend docs](https://www.pulumi.com/docs/iac/operations/stack-management/using-a-diy-backend/#azure-blob-storage) for the full URL syntax and alternative authentication options.

5. Install the project's Python dependencies into a virtual environment:

   ```bash
   uv sync
   ```

6. Select (or create) a stack and deploy:

   ```bash
   pulumi stack select dev   # or: pulumi stack init dev
   pulumi up
   ```

7. To tear down the deployed infrastructure:

   ```bash
   pulumi destroy
   ```

## For contributors: setting up a development environment

1. Follow the [prerequisites](#prerequisites) above, then install the dev dependencies:

   ```bash
   uv sync
   ```

   This installs `pulumi`, `pulumi-azure-native`, plus the dev tools (`ruff`, `ty`, `pytest`) into a local `.venv`, driven entirely by `pyproject.toml` / `uv.lock`.

2. Run the program locally:

   ```bash
   pulumi preview
   ```

3. Lint and format code with [ruff](https://docs.astral.sh/ruff/):

   ```bash
   uv run ruff check .
   uv run ruff format .
   ```

4. Type-check with [ty](https://docs.astral.sh/ty/):

   ```bash
   uv run ty check
   ```

5. Run the test suite (unit tests use Pulumi's built-in mocking framework, so no cloud credentials are needed):

   ```bash
   uv run pytest
   ```

6. Before opening a pull request, make sure `ruff check`, `ruff format --check`, `ty check`, and `pytest` all pass.

### Project structure

- `Pulumi.yaml` — project definition
- `Pulumi.<stack>.yaml` — per-stack configuration (e.g. `Pulumi.dev.yaml`)
- `__main__.py` — program entry point
- `infra.py` — infrastructure resource definitions, imported by `__main__.py` and by the test suite
- `tests/` — unit tests using Pulumi's mocking framework
- `pyproject.toml` / `uv.lock` — dependency manifest and lockfile managed by uv
