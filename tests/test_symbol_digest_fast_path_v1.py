from __future__ import annotations

import unittest

from noetrium_platform.foundation.kernel.kernel import (
    strict_finite_json_digest,
)
import noetrium_platform.foundation.kernel.structure as structure
from noetrium_platform.foundation.kernel.unit import _unit_structural_digest


class SymbolDigestFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        with structure._PARAMETERIZED_SYMBOL_CACHE_LOCK:
            structure._PARAMETERIZED_SYMBOL_CACHE.clear()
            structure._PARAMETERIZED_SYMBOL_PREFIX_INDEX.clear()
        structure._empty_parameter_symbol_unit.cache_clear()

    def _assert_generic_identity(self, parameters: object) -> None:
        unit = structure.symbol_unit(
            "probe.symbol",
            ("research.configuration",),
            parameters=parameters,
        )
        expected_semantic = strict_finite_json_digest(
            {
                "symbol_id": "probe.symbol",
                "traits": ("research.configuration",),
                "implementation_digest": None,
                "parameters": parameters,
            }
        )
        expected_structural = _unit_structural_digest(
            unit.schemas,
            unit.attributes,
            unit.roles,
        )
        self.assertEqual(unit.semantic_digest, expected_semantic)
        self.assertEqual(unit.structural_digest, expected_structural)

    def test_direct_digests_equal_generic_contract(self) -> None:
        for parameters in (
            {"a": 1},
            {"nested": {"x": "y", "rows": [1, 2, 3]}},
            {"tuple": (1, "x", False), "float": 1.25},
            {"zero": -0.0},
        ):
            with self.subTest(parameters=parameters):
                self._assert_generic_identity(parameters)

    def test_fast_lookup_never_aliases_distinct_json_scalars(self) -> None:
        negative_zero = structure.symbol_unit(
            "probe.scalar",
            ("research.configuration",),
            parameters={"value": -0.0},
        )
        positive_zero = structure.symbol_unit(
            "probe.scalar",
            ("research.configuration",),
            parameters={"value": 0.0},
        )
        boolean = structure.symbol_unit(
            "probe.boolean",
            ("research.configuration",),
            parameters={"value": True},
        )
        integer = structure.symbol_unit(
            "probe.boolean",
            ("research.configuration",),
            parameters={"value": 1},
        )
        self.assertNotEqual(
            negative_zero.semantic_digest,
            positive_zero.semantic_digest,
        )
        self.assertNotEqual(boolean.semantic_digest, integer.semantic_digest)

    def test_json_array_equivalence_hits_same_unit(self) -> None:
        left = structure.symbol_unit(
            "probe.array",
            ("research.configuration",),
            parameters={"value": [1, 2, 3]},
        )
        right = structure.symbol_unit(
            "probe.array",
            ("research.configuration",),
            parameters={"value": (1, 2, 3)},
        )
        self.assertIs(left, right)

    def test_mutated_input_cannot_reuse_stale_symbol(self) -> None:
        parameters = {"value": 1}
        first = structure.symbol_unit(
            "probe.mutable",
            ("research.configuration",),
            parameters=parameters,
        )
        parameters["value"] = 2
        second = structure.symbol_unit(
            "probe.mutable",
            ("research.configuration",),
            parameters=parameters,
        )
        self.assertNotEqual(first.semantic_digest, second.semantic_digest)
        self.assertNotEqual(first.unit_digest, second.unit_digest)


if __name__ == "__main__":
    unittest.main()


def test_many_distinct_same_prefix_symbols_have_constant_size_prefix_cache():
    structure._PARAMETERIZED_SYMBOL_CACHE.clear()
    structure._PARAMETERIZED_SYMBOL_PREFIX_INDEX.clear()
    samples=[]
    for index in range(1700):
        samples.append(structure.symbol_unit(
            'large-shared-namespace',('research.configuration',),
            parameters={'index':index,'nested':{'step':index}},
        ))
    prefix=('large-shared-namespace',('research.configuration',),None)
    assert len(structure._PARAMETERIZED_SYMBOL_PREFIX_INDEX)==1
    assert isinstance(structure._PARAMETERIZED_SYMBOL_PREFIX_INDEX[prefix],str)
    assert len({unit.unit_digest for unit in samples})==1700
    # A cold cache hit in an old position uses the canonical digest lookup;
    # repeating that symbol becomes an O(1)-candidate temporal hit.
    assert structure.symbol_unit(
        'large-shared-namespace',('research.configuration',),
        parameters={'index':12,'nested':{'step':12}},
    ) is samples[12]
    assert structure.symbol_unit(
        'large-shared-namespace',('research.configuration',),
        parameters={'index':12,'nested':{'step':12}},
    ) is samples[12]


def test_parallel_distinct_parameters_preserve_injective_symbol_identities():
    from concurrent.futures import ThreadPoolExecutor
    def construct(index):
        return structure.symbol_unit(
            'multi-paper-shared-symbol',('research.configuration',),
            parameters={'case':index,'enabled':bool(index%2)},
        )
    with ThreadPoolExecutor(max_workers=8) as workers:
        symbols=tuple(workers.map(construct,range(1300)))
    assert len({symbol.semantic_digest for symbol in symbols})==len(symbols)
    with ThreadPoolExecutor(max_workers=8) as workers:
        second=tuple(workers.map(construct,range(1300)))
    assert all(left is right for left,right in zip(symbols,second))
    prefix=('multi-paper-shared-symbol',('research.configuration',),None)
    assert isinstance(structure._PARAMETERIZED_SYMBOL_PREFIX_INDEX[prefix],str)
