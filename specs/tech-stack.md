# Tech Stack

Minimum tech stack for a Pulumi program that deploys Azure infrastructure using Python.

## Core

- **Python** — 3.11 or later
- **Pulumi CLI** — latest stable release
- **pulumi** — core Pulumi SDK for Python
- **pulumi-azure-native** — Azure Resource Manager provider (preferred over the classic `pulumi-azure` provider for full, up-to-date ARM API coverage)

## Azure Authentication

- **Azure CLI** (`az`) — the only supported authentication method, used for local and CI/CD authentication (`az login`) so Pulumi can pick up credentials via the default Azure credential chain

## Environment & Dependency Management

- **uv** — used exclusively to manage the Python virtual environment and project dependencies (replaces `venv`/`pip`/`pip-tools`)
  - `uv venv` to create the virtual environment
  - `uv add` / `uv sync` to manage and install dependencies
  - `pyproject.toml` as the single source of truth for dependencies, with `uv.lock` committed for reproducible installs

## Code Quality

- **Astral** tooling for linting, formatting, and type checking:
  - **ruff** — linter and formatter
  - **ty** — type checker

## State Backend

- **Azure Blob Storage** — the Pulumi state backend, self-managed via `pulumi login azblob://<container>`

## Project Structure

- `Pulumi.yaml` — project definition
- `Pulumi.<stack>.yaml` — per-stack configuration (e.g., `dev`, `prod`)
- `__main__.py` — program entry point
- `pyproject.toml` / `uv.lock` — dependency manifest and lockfile managed by uv
