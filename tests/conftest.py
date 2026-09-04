"""Shared Pulumi test setup.

Runs at collection time, before any test module imports `infra`, so every
`infra` submodule can rely on mocks already being in place.
"""

import pulumi

_RESULT_ONLY_TYPES = {
    "random:index/randomString:RandomString",
    "random:index/randomPassword:RandomPassword",
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
        return {}


pulumi.runtime.set_mocks(AzureMocks(), project="rse-cloud-cybersecurity", stack="test")
