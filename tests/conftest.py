"""Shared Pulumi test setup.

Runs at collection time, before any test module imports `infra`, so every
`infra` submodule can rely on mocks (and the environment variables `infra`
reads at module-evaluation time) already being in place.
"""

import os

import pulumi

# infra.database reads these from the environment at import time (see
# specs/01-managing-identity.md), so they must be set before any test module
# imports `infra` - too late to set them per-test via monkeypatch.
os.environ.setdefault("AAD_ADMIN_OBJECT_ID", "11111111-1111-1111-1111-111111111111")
os.environ.setdefault("AAD_ADMIN_LOGIN", "aad-admin@example.com")

_RESULT_ONLY_TYPES = {
    "random:index/randomString:RandomString",
    "random:index/randomPassword:RandomPassword",
    "random:index/randomUuid:RandomUuid",
}

_MOCK_CALL_RESULTS = {
    "azure-native:authorization:getClientConfig": {
        "subscriptionId": "00000000-0000-0000-0000-000000000000",
        "tenantId": "11111111-1111-1111-1111-111111111111",
        "clientId": "22222222-2222-2222-2222-222222222222",
        "objectId": "33333333-3333-3333-3333-333333333333",
    },
}


class AzureMocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        outputs = args.inputs
        if args.typ in _RESULT_ONLY_TYPES:
            # `result` is an output-only property the real provider computes;
            # the mock's inputs echo doesn't include it, so synthesize one.
            outputs = {**args.inputs, "result": f"{args.name}-mock-result"}
        return [f"{args.name}_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return _MOCK_CALL_RESULTS.get(args.token, {})


pulumi.runtime.set_mocks(AzureMocks(), project="rse-cloud-cybersecurity", stack="test")
