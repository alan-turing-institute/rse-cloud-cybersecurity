# rse-cloud-cybersecurity

A repository for the "Cloud Cybersecurity for Research Engineers​" presentation at RSECON26.

This repository contains a [Pulumi](https://www.pulumi.com/) program, written in Python, that deploys Azure infrastructure. See [`specs/tech-stack.md`](specs/tech-stack.md) for the full technology stack.

## Prerequisites

- [Python](https://www.python.org/) 3.11 or later
- [uv](https://docs.astral.sh/uv/) for Python environment and dependency management
- [Pulumi CLI](https://www.pulumi.com/docs/iac/download-install/)
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`), authenticated via `az login` — this is the only supported way to authenticate against Azure
- An Azure Blob Storage container to use as the Pulumi state backend

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

3. Log Pulumi in to the Azure Blob Storage state backend:

   ```bash
   pulumi login azblob://<container>
   ```

4. Install the project's Python dependencies into a virtual environment:

   ```bash
   uv sync
   ```

5. Select (or create) a stack and deploy:

   ```bash
   pulumi stack select dev   # or: pulumi stack init dev
   pulumi up
   ```

6. To tear down the deployed infrastructure:

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
