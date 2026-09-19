from tests_support import FakeParticipantResolver
from tests_support import context_action_spec, runtime_identity_for_test
import hashlib
import unittest

from noetrium_platform.capabilities.environment.runtime.api import action_request_digest, EnvironmentIdentity, Observation, ActionResult
from noetrium_platform.foundation.kernel.kernel import EffectReceipt, EffectClass, EffectCertainty
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot, RecallResult
from noetrium_platform.capabilities.participant.binding.runtime.configuration import ParticipantConfigurationCatalog
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantConfigurationArtifact, ParticipantImplementationIdentity
from noetrium_platform.capabilities.participant.definition.runtime.catalog import ParticipantImplementationCatalog
from noetrium_platform.capabilities.participant.binding.runtime import LocalParticipantResolver
from noetrium_platform.capabilities.participant.session.runtime.runtime_catalog import ParticipantSessionRuntimeCatalog
from noetrium_platform.capabilities.participant.session.runtime.runtime_endpoint import LocalParticipantRuntimeEndpoint
from noetrium_platform.composition.context_action import compose_context_action_runtime


class MSession:
    def ingest(self,e,c): pass
    def recall(self,r): return RecallResult("ctx","g0")
    def task_completed(self,r,c): pass
    def checkpoint(self): return MethodSnapshot("m","1","1","","s","d",b"")
    def restore(self,s): pass
    def diagnostics(self): return {}
    def close(self): pass
class MethodA:
    identity=MethodIdentity("m","1","1","1")
    def open_session(self,*,session_id,services): return MSession()
class ESession:
    def observe(self,c): return Observation("o","e0",{})
    def act(self,r): return ActionResult(r.action_id,True,None,EffectReceipt("fx",action_request_digest(r),EffectClass.IDEMPOTENT,EffectCertainty.NO_EFFECT),{})
    def reconcile(self,e,c): return e
    def checkpoint(self): return b""
    def restore(self,p): pass
    def close(self): pass
class EnvA:
    identity=EnvironmentIdentity("e","1","1","1")
    def open_session(self,*,session_id,services): return ESession()



class DelegatingRuntime:
    def __init__(self, identity): self._identity=identity
    @property
    def runtime_identity(self): return self._identity
    def open_session(self, implementation, *, session_id, services):
        return implementation.open_session(session_id=session_id, services=services)

class StudyIdentityFreezeV107Tests(unittest.TestCase):
    def _runtime(self, *, known_method_config: str = "", known_environment_config: str = ""):
        implementations = ParticipantImplementationCatalog()
        runtimes = ParticipantSessionRuntimeCatalog()
        configurations = ParticipantConfigurationCatalog()
        method_impl = ParticipantImplementationIdentity("method", "m", "1", "1", "1")
        environment_impl = ParticipantImplementationIdentity("environment", "e", "1", "1", "1")
        implementations.register(method_impl, lambda config: MethodA())
        implementations.register(environment_impl, lambda config: EnvA())
        method_runtime = runtime_identity_for_test("method")
        environment_runtime = runtime_identity_for_test("environment")
        runtimes.register(method_runtime, lambda: DelegatingRuntime(method_runtime))
        runtimes.register(environment_runtime, lambda: DelegatingRuntime(environment_runtime))
        configurations.register(ParticipantConfigurationArtifact(hashlib.sha256(b"method:m:configuration").hexdigest(), b"method-default"))
        configurations.register(ParticipantConfigurationArtifact(hashlib.sha256(b"environment:e:configuration").hexdigest(), b"environment-default"))
        if known_method_config:
            configurations.register(ParticipantConfigurationArtifact(hashlib.sha256(known_method_config.encode()).hexdigest(), b"method-config"))
        if known_environment_config:
            configurations.register(ParticipantConfigurationArtifact(hashlib.sha256(known_environment_config.encode()).hexdigest(), b"environment-config"))
        return compose_context_action_runtime(LocalParticipantResolver(
            implementations,
            runtimes,
            configurations,
            LocalParticipantRuntimeEndpoint,
        ))

    def test_unknown_method_configuration_fails_during_participant_resolution(self):
        spec=context_action_spec("study","m","e",method_configuration_digest="method-B")
        with self.assertRaises(Exception) as raised:
            self._runtime().execute_cycle(spec,task="x",input_kind="a",input_payload={})
        self.assertIn("method.resolve", str(raised.exception))

    def test_unknown_environment_configuration_fails_during_participant_resolution(self):
        spec=context_action_spec("study","m","e",environment_configuration_digest="env-B")
        with self.assertRaises(Exception) as raised:
            self._runtime().execute_cycle(spec,task="x",input_kind="a",input_payload={})
        self.assertIn("environment.resolve", str(raised.exception))

    def test_runtime_configuration_changes_study_identity_without_changing_implementation_identity(self):
        a=context_action_spec("study","m","e",method_configuration_digest="method-A",environment_configuration_digest="env-A")
        b=context_action_spec("study","m","e",method_configuration_digest="method-B",environment_configuration_digest="env-A")
        self.assertNotEqual(a.identity_digest(),b.identity_digest())
        self.assertEqual(a.participants[0].implementation.digest(), b.participants[0].implementation.digest())
        result=self._runtime(known_method_config="method-A",known_environment_config="env-A").execute_cycle(a,task="x",input_kind="a",input_payload={})
        self.assertEqual(result.context_text,"ctx")


if __name__=='__main__': unittest.main()
