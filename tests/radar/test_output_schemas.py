"""The two frozen LLM output schemas use only keywords the strict path honours (PF1, T4.0).

Strict json_schema on Token Factory is confirmed for exactly these keywords:
type, properties, required, items, $defs, $ref, enum, maxItems, anyOf (with null),
additionalProperties, title, default. Anything else (description, pattern, minLength, format,
const, oneOf) is unconfirmed, so the output models must not emit it.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from northvaine.brain import llm
from northvaine.core.settings import Settings
from northvaine.radar.extract import ExtractionOutput
from northvaine.radar.verify import SupportOutput

ALLOWED = {
    "type", "properties", "required", "items", "$defs", "$ref", "enum", "maxItems", "anyOf",
    "additionalProperties", "title", "default",
}  # fmt: skip
FORBIDDEN = {"description", "pattern", "minLength", "maxLength", "format", "const", "oneOf"}
MODELS = [ExtractionOutput, SupportOutput]


def keywords(node: Any) -> set[str]:
    """Every schema keyword used under `node`; names under `properties`/`$defs` are not keywords."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for child in value.values():
                    found |= keywords(child)
            elif key != "default":
                found |= keywords(value)
    elif isinstance(node, list):
        for item in node:
            found |= keywords(item)
    return found


def any_ofs(node: Any) -> list[list[Any]]:
    found: list[list[Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "anyOf":
                found.append(value)
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for child in value.values():
                    found += any_ofs(child)
            elif key != "default":
                found += any_ofs(value)
    elif isinstance(node, list):
        for item in node:
            found += any_ofs(item)
    return found


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_schema_uses_only_confirmed_keywords(model: type[BaseModel]) -> None:
    used = keywords(model.model_json_schema())
    assert used <= ALLOWED, sorted(used - ALLOWED)
    assert not used & FORBIDDEN


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_any_of_is_a_type_or_null(model: type[BaseModel]) -> None:
    unions = any_ofs(model.model_json_schema())
    for members in unions:
        assert len(members) == 2, members
        assert members[-1] == {"type": "null"}, members
        assert members[0] != {"type": "null"}, members


def test_extraction_output_has_nullable_fields() -> None:
    assert any_ofs(ExtractionOutput.model_json_schema())


def test_support_output_has_no_free_form_object_or_union() -> None:
    schema = SupportOutput.model_json_schema()
    assert not any_ofs(schema)
    assert "oneOf" not in str(schema)


def test_slots_are_a_list_of_name_value_pairs_not_a_free_form_object() -> None:
    defs = ExtractionOutput.model_json_schema()["$defs"]
    slot = defs["SlotValue"]
    assert set(slot["properties"]) == {"name", "value"}
    slots = defs["ExtractedEvent"]["properties"]["slots"]
    assert slots["type"] == "array" and slots["items"] == {"$ref": "#/$defs/SlotValue"}


def test_output_models_have_no_docstrings_and_no_field_descriptions() -> None:
    from northvaine.radar import extract, verify

    for cls in (
        extract.ExtractedClaim, extract.ExtractedEvent, extract.ExtractionOutput,
        extract.SlotValue, verify.SupportVerdict, verify.SupportOutput,
    ):  # fmt: skip
        assert cls.__doc__ is None, cls.__name__
        assert all(f.description is None for f in cls.model_fields.values()), cls.__name__


def test_max_items_literal_agrees_with_the_extract_max_claims_default() -> None:
    schema = ExtractionOutput.model_json_schema()
    default = Settings(_env_file=None).extract_max_claims
    assert schema["properties"]["claims"]["maxItems"] == default
    assert schema["properties"]["events"]["maxItems"] == default


def test_frozen_field_names() -> None:
    from northvaine.radar import extract, verify

    assert list(extract.ExtractedClaim.model_fields) == [
        "statement", "source_quote", "subject_name", "subject_country", "subject_role",
    ]  # fmt: skip
    assert list(extract.ExtractedEvent.model_fields) == [
        "event_type", "claim_indices", "subject_name", "date_text", "group_hint", "slots",
        "concept_label", "concept_hint",
    ]  # fmt: skip
    assert list(extract.ExtractionOutput.model_fields) == ["claims", "events"]
    assert list(extract.SlotValue.model_fields) == ["name", "value"]
    assert list(verify.SupportVerdict.model_fields) == ["index", "supported"]
    assert list(verify.SupportOutput.model_fields) == ["verdicts"]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_build_request_nests_the_schema_and_is_strict(model: type[BaseModel]) -> None:
    body = llm.build_request(
        model="m", rendered="hi", max_tokens=10, reasoning_effort="none", output_model=model
    )
    spec = body["response_format"]
    assert spec["type"] == "json_schema"
    assert spec["json_schema"]["strict"] is True
    assert spec["json_schema"]["name"] == model.__name__
    assert spec["json_schema"]["schema"] == model.model_json_schema()


def test_extraction_output_accepts_a_reply_with_nulls() -> None:
    reply = (
        '{"claims": [{"statement": "s", "source_quote": "q", "subject_name": null,'
        ' "subject_country": null, "subject_role": null}],'
        ' "events": [{"event_type": "t", "claim_indices": [0], "subject_name": null,'
        ' "date_text": null, "group_hint": null, "slots": [{"name": "n", "value": "v"}],'
        ' "concept_label": null, "concept_hint": null}]}'
    )
    out = ExtractionOutput.model_validate_json(reply)
    assert out.claims[0].subject_name is None
    assert out.events[0].slots[0].value == "v"
