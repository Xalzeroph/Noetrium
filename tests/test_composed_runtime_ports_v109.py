from __future__ import annotations

import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimePlatformAuthorities


class Unary:
    def __init__(self, name: str):
        self.name = name
    def verify(self, manifest):
        return (self.name,)


class Binary:
    def __init__(self, name: str):
        self.name = name
    def verify(self, manifest, deployments):
        return (self.name,)


class Services:
    def reconcile(self, manifest, deployments): return ("svc-reconcile",)
    def start_exact(self, manifest, deployments): return ("svc-start",)
    def verify_ready(self, manifest, deployments): return ("svc-ready",)
    def final_status(self, manifest, deployments): return ("svc-final",)


class Study:
    def reconcile(self, manifest): return ("run-reconcile",)
    def start_exact(self, manifest): return ("study-start",)
    def final_status(self, manifest): return ("run-final",)


class RuntimePlatformAuthoritiesV109Tests(unittest.TestCase):
    def test_bundle_contains_only_narrow_authorities_and_no_orchestration_methods(self):
        authorities = RuntimePlatformAuthorities(
            Unary("release"), Unary("prompts"), Binary("deployments"), Services(), Binary("qualification"),
            Unary("implementations"), Unary("runtimes"), Unary("bindings"), Study(),
        )
        self.assertFalse(hasattr(authorities, "verify_release"))
        self.assertFalse(hasattr(authorities, "start_exact_services"))
        self.assertFalse(hasattr(authorities.release, "start_exact"))
        self.assertFalse(hasattr(authorities.run, "verify"))
        self.assertIsInstance(authorities.services, Services)


if __name__ == "__main__":
    unittest.main()
