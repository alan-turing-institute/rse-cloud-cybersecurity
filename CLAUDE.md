# CLAUDE.md

Guidance for working on this repository: the tech stack it's built with, and the coding guidelines to follow when changing it.

## Tech stack

Minimum tech stack for a Pulumi program that deploys Azure infrastructure using Python.

### Core

- **Python** — 3.11 or later
- **Pulumi CLI** — latest stable release
- **pulumi** — core Pulumi SDK for Python
- **pulumi-azure-native** — Azure Resource Manager provider (preferred over the classic `pulumi-azure` provider for full, up-to-date ARM API coverage)

### Azure Authentication

- **Azure CLI** (`az`) — the only supported authentication method, used for local and CI/CD authentication (`az login`) so Pulumi can pick up credentials via the default Azure credential chain

### Environment & Dependency Management

- **uv** — used exclusively to manage the Python virtual environment and project dependencies (replaces `venv`/`pip`/`pip-tools`)
  - `uv venv` to create the virtual environment
  - `uv add` / `uv sync` to manage and install dependencies
  - `pyproject.toml` as the single source of truth for dependencies, with `uv.lock` committed for reproducible installs

### Code Quality

- **Astral** tooling for linting, formatting, and type checking:
  - **ruff** — linter and formatter
  - **ty** — type checker

### Testing

- **Pulumi's testing facilities** (`pulumi.runtime.set_mocks` / unit testing framework) — used to test the Pulumi program's resources and logic before deployment

### State Backend

- **Azure Blob Storage** — the Pulumi state backend, self-managed via `pulumi login azblob://<container>`

### Project Structure

- `Pulumi.yaml` — project definition
- `Pulumi.<stack>.yaml` — per-stack configuration (e.g., `dev`, `prod`)
- `__main__.py` — program entry point
- `pyproject.toml` / `uv.lock` — dependency manifest and lockfile managed by uv

## Coding guidelines

### No live deployments as part of building a feature

Claude **should not** run any command that deploys, modifies, or destroys resources in the Azure cloud (e.g. `pulumi up`, `pulumi destroy`, or direct `az` commands that create/change/delete resources) as part of implementing or verifying a feature.

Verification of Pulumi program changes must rely **only** on:

- Unit tests using Pulumi's mocking framework (`pulumi.runtime.set_mocks` / `pulumi.runtime.test`), run via `uv run pytest`.
- Static checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`.
- `pulumi preview` is a borderline case: it does not deploy anything, but it does require live Azure credentials and reaches out to Azure to diff against real state. Do not run it unless the user explicitly asks for it in the moment.

Deploying and validating the actual deployed resources is done **manually** by a human, not by Claude. This keeps cloud spend, blast radius, and account access fully in the user's control.

**Why:** deployments are hard-to-reverse actions with real cost and access implications on shared cloud infrastructure. Relying on mocked unit tests keeps feature work fast, repeatable, and free, and keeps a human in the loop for anything that actually touches Azure.

**How to apply:** when implementing or changing infrastructure code in this repository, write/extend unit tests and run the checks above to verify the change. Do not run `pulumi up`, `pulumi destroy`, or other resource-mutating `az`/`pulumi` commands yourself. If manual deployment or validation is needed, say so and let the user run it.

### Module layout: constants before functions/classes

Within a Python module, place module-level constants immediately after the imports, before any function or class definitions. Functions and classes come after the constants they use.

**Why:** a reader scanning a module top-to-bottom should see the fixed configuration values before the logic that consumes them, rather than having to jump around the file to find where a name used mid-function is defined.

**How to apply:** when writing or editing a module, group `UPPER_CASE` (or other) module-level constants together at the top, right after `import`s, and put `def`/`class` definitions below them.

### Prefer Jinja templates over assembling YAML in code

When a module needs to produce YAML content (e.g. cloud-init user-data, Pulumi resource bodies expressed as YAML), render it from a Jinja template rather than building the text programmatically (string formatting, f-strings, list-joining, etc.) in Python.

**Why:** hand-assembled YAML is easy to get subtly wrong — e.g. a value containing `key: value`-shaped text breaks YAML's plain-scalar parsing unless it's quoted, which is easy to miss when the content is built up piecemeal in Python rather than written as YAML. A `.j2` template keeps the YAML structure readable as YAML, with only the truly dynamic bits substituted in.

**How to apply:** write the YAML as a Jinja template file (e.g. `cloud-init.yaml.j2`) and render it with the dynamic values (via `jinja2.Template`/`Environment`), instead of concatenating strings or building lists of lines to join into YAML.
