from __future__ import annotations

from typing import TypeVar, cast

from noetrium_platform.evidence.data.fact.api import (
    DurableFact,
    FactCriticality,
    FactDecoderPort,
    FactSchema,
    UnknownRequiredFact,
)

TDecoded = TypeVar("TDecoded")


class FactDecoderRegistry:
    def __init__(self, decoders: tuple[FactDecoderPort[object], ...] = ()) -> None:
        self._decoders = {
            (decoder.schema.fact_type, decoder.schema.schema_version): decoder
            for decoder in decoders
        }

    def decoder_for(self, schema: FactSchema[TDecoded]) -> FactDecoderPort[TDecoded]:
        decoder = self._decoders.get((schema.fact_type, schema.schema_version))
        if decoder is None:
            raise UnknownRequiredFact(
                f"unknown required fact schema: {schema.fact_type}@{schema.schema_version}"
            )
        return cast(FactDecoderPort[TDecoded], decoder)

    def decode_as(self, fact: DurableFact, schema: FactSchema[TDecoded]) -> TDecoded:
        if (fact.fact_type, fact.schema_version) != (schema.fact_type, schema.schema_version):
            raise ValueError("durable fact does not match requested typed schema")
        return self.decoder_for(schema).decode(fact)

    def decode(self, fact: DurableFact):
        decoder = self._decoders.get((fact.fact_type, fact.schema_version))
        if decoder is None:
            if fact.criticality is FactCriticality.IGNORABLE:
                return None
            raise UnknownRequiredFact(
                f"unknown required fact: {fact.fact_type}@{fact.schema_version}"
            )
        return decoder.decode(fact)


__all__ = ["FactDecoderRegistry"]
