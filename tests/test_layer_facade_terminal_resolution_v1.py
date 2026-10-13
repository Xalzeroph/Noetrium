"""A generated facade must prove terminal ownership before any write."""
from types import SimpleNamespace
import pytest
from scripts.generate_layer_facades import resolve_contract


def test_unknown_contract_cannot_be_fabricated_on_terminal_facade(monkeypatch):
    monkeypatch.setattr('scripts.generate_layer_facades.importlib.import_module', lambda name: SimpleNamespace())
    with pytest.raises(RuntimeError, match='terminal facade terminal.api does not export it'):
        resolve_contract(layer_id='capability', name='MissingContract', facade_module=None,
                         member_apis=('member.api',), lower_facade='terminal.api')


def test_manually_owned_terminal_contract_is_resolved(monkeypatch):
    def module(name):
        return SimpleNamespace(Contract=object()) if name == 'terminal.api' else SimpleNamespace()
    monkeypatch.setattr('scripts.generate_layer_facades.importlib.import_module', module)
    assert resolve_contract(layer_id='capability', name='Contract', facade_module=None,
                            member_apis=('member.api',), lower_facade='terminal.api') == 'terminal.api'


def test_generated_lower_layer_can_defer_until_its_own_resolution_pass(monkeypatch):
    monkeypatch.setattr('scripts.generate_layer_facades.importlib.import_module', lambda name: SimpleNamespace())
    assert resolve_contract(layer_id='capability', name='Contract', facade_module=None,
                            member_apis=('member.api',), lower_facade='generated.api',
                            deferred_facades=frozenset({'generated.api'})) == 'generated.api'
