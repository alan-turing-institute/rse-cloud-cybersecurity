# Coding Guidelines

## No live deployments as part of building a feature

Claude **should not** run any command that deploys, modifies, or destroys resources in the Azure cloud (e.g. `pulumi up`, `pulumi destroy`, or direct `az` commands that create/change/delete resources) as part of implementing or verifying a feature.

Verification of Pulumi program changes must rely **only** on:

- Unit tests using Pulumi's mocking framework (`pulumi.runtime.set_mocks` / `pulumi.runtime.test`), run via `uv run pytest`.
- Static checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`.
- `pulumi preview` is a borderline case: it does not deploy anything, but it does require live Azure credentials and reaches out to Azure to diff against real state. Do not run it unless the user explicitly asks for it in the moment.

Deploying and validating the actual deployed resources is done **manually** by a human, not by Claude. This keeps cloud spend, blast radius, and account access fully in the user's control.

**Why:** deployments are hard-to-reverse actions with real cost and access implications on shared cloud infrastructure. Relying on mocked unit tests keeps feature work fast, repeatable, and free, and keeps a human in the loop for anything that actually touches Azure.

**How to apply:** when implementing or changing infrastructure code in this repository, write/extend unit tests and run the checks above to verify the change. Do not run `pulumi up`, `pulumi destroy`, or other resource-mutating `az`/`pulumi` commands yourself. If manual deployment or validation is needed, say so and let the user run it.
