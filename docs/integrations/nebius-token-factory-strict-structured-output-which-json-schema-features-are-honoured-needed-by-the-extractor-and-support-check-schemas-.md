# Token Factory strict structured output: which JSON Schema features are honoured

Date checked: 2026-10-04
Model: `nvidia/Nemotron-3_5-Lightning` (fast tier), `reasoning_effort: "none"`, `strict: true`.
Source: live probe (3 calls, about 340 tokens total, well under $0.0001). The Nebius docs do not
list supported JSON Schema keywords, so everything below is empirical, not from docs.

## Summary

`$defs` / `$ref` (Pydantic nested models) are accepted and the output obeys them. Arrays of
objects, string `enum`, `maxItems` and `anyOf: [X, null]` are all accepted (HTTP 200) and
the constraints were visibly enforced. No ref-inliner is needed in `llm.build_request`.

Caveat: the T4.0 `ExtractionOutput` model does not exist yet (no M4 board, no such class in the
repo), so the probe used a stand-in with the same shape: `ExtractionOutput{claims: list[ClaimOut]}`,
`ClaimOut{field: enum, value, source_quote, note: str|None}`, built as Pydantic emits it
(`$defs`, `$ref`, `title`, `default`, `additionalProperties: false`). Re-run the probe on the real
schema once T4.0 freezes it (script below).

## Facts table

| # | Question | Result | Confidence |
|---|---|---|---|
| 1 | `$defs` + `$ref: "#/$defs/X"` accepted with strict=true | HTTP 200; output has the nested object shape | confirmed live |
| 2 | `$ref` output identical to inlined schema | Yes: byte-identical content, same token counts (104 in / 65 out) | confirmed live |
| 3 | Array of objects (`items` via `$ref`) | Accepted, produced valid objects | confirmed live |
| 4 | `maxItems` | Enforced: prompt asked for "at least 5 claims", text held 8+ facts, output had exactly 2 with `maxItems: 2` | confirmed live (one case) |
| 5 | `enum` on a string field | Enforced: text contained an injected instruction to add a field "colour"; output used only enum values and no extra keys | confirmed live (one case) |
| 6 | `additionalProperties: false` | Accepted, and no extra keys appeared | confirmed live |
| 7 | `anyOf: [{type: string}, {type: null}]` (Pydantic `str \| None`) | Accepted (HTTP 200); with `note` required, output filled it with strings | accepted: confirmed. Emitting `null` itself: not observed, unverified |
| 8 | `title`, `default` keywords | Accepted, no error | confirmed live |
| 9 | Behaviour on unsupported keywords | Not probed (no rejection seen for any keyword used). Untested: `minItems`, `minLength`, `pattern`, `format`, `oneOf`, recursive `$ref` | unknown |
| 10 | Is enforcement real constrained decoding or just prompt-following? | Cannot tell from 3 calls. The `maxItems` and `enum` results went against the prompt's pressure, which suggests decoding-level enforcement, but `llm.py` must still Pydantic-validate every reply (rule 8) | inferred |

## Probe request (shape used)

```json
{"model": "nvidia/Nemotron-3_5-Lightning", "max_tokens": 400, "temperature": 0,
 "reasoning_effort": "none",
 "response_format": {"type": "json_schema", "json_schema": {
   "name": "ExtractionOutput", "strict": true,
   "schema": {"$defs": {"ClaimOut": {"type": "object", "properties": {
                "field": {"type": "string", "enum": ["product", "country", "volume"]},
                "value": {"type": "string"}, "source_quote": {"type": "string"},
                "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}},
              "required": ["field", "value", "source_quote"], "additionalProperties": false}},
     "type": "object",
     "properties": {"claims": {"type": "array", "maxItems": 2, "items": {"$ref": "#/$defs/ClaimOut"}}},
     "required": ["claims"], "additionalProperties": false}}}}
```

Reply (HTTP 200, `finish_reason: stop`): two claims only, valid enum values, no extra keys.

## Recommendation for T4.0

- Keep `output_model.model_json_schema()` as is; no ref-inliner.
- Still validate with Pydantic after the call; treat server-side enforcement as a bonus.
- Do not rely on keywords not in row 9 without a probe. If `ExtractionOutput` uses `minLength`,
  `pattern` or `oneOf`, probe them first.
- Enforce "`source_quote` appears in `documents.text`" in code, never via schema.

## Open questions

1. Real `ExtractionOutput` and support-check schemas: not yet frozen, probed only a stand-in.
2. Null emission for `anyOf` with null, and the untested keywords in row 9.
3. The task asked to append this result to
   `docs/integrations/nebius-token-factory-api-surface-and-client.md`; that edit was outside the
   "only this file" limit, so the orchestrator should append a pointer to this note.

To re-run on the real schema (does not print the key):
`uv run python -c "from northvaine.brain.llm import ...; print(ExtractionOutput.model_json_schema())"`,
then POST it as `response_format.json_schema.schema` with `strict: true` and `reasoning_effort: "none"`.

## PF1b on the frozen schemas (2026-10-04)

Source: live calls on main (T4.0 merged), checked 2026-10-04. Confidence: confirmed by live call.
Method: `llm.build_request()` (exact body llm.py sends: `temperature 0`, `max_tokens 600`,
`reasoning_effort: "none"`, `response_format.json_schema{name, strict: true, schema}`) posted with the
openai SDK directly (not `complete_json`) so no `llm_calls` row was written; production DB is at 0004
and the ledger write path was deliberately not exercised. Fast tier model from `MODEL_FAST`.
No key, .env line or connection string appears below.

| | ExtractionOutput | SupportOutput |
|---|---|---|
| Schema keywords present | `$defs, $ref, anyOf, default, items, maxItems, properties, required, title, type` | `$defs, $ref, items, properties, required, title, type` |
| Keywords outside the allow-list | none (`additionalProperties`/`enum` not emitted by these models) | none |
| HTTP status | 200 | 200 |
| finish_reason | stop | stop |
| Tokens in/out | 102 / 168 | 93 / 31 |
| Validated by Pydantic | yes | yes |
| Cost (pricing.json) | $0.0000464 | $0.0000130 |

Total spend: about $0.00006 (two calls). No keyword rejected.

Null behaviour (ExtractionOutput, nullable fields are `anyOf [string, null]`, `default null`, not in
`required`): the model returned an explicit `"group_hint": null` where the text gave no group.
Other nullable fields (`date_text`, `concept_label`, `concept_hint`, `subject_country`, ...) were
omitted rather than sent as null; that validates because they are not `required`. Code must treat
absent and null identically (Pydantic does, via the default).

Excerpts (redacted, no secrets present):
- Extraction: `{"claims": [], "events": [{"event_type": "contract_signing", "claim_indices": [], "subject_name": "Acme Tiles Ltd", "group_hint": null, "slots": [{"name": "subject_country", "value": "Portugal"}, ...]}]}`
- Support: `{"verdicts": [{"index": 0, "supported": true}, {"index": 1, "supported": false}]}` (second claim was deliberately unsupported; correct).

Observations (not schema failures): with my ad hoc prompt the model returned empty `claims` and put
claim-like fields into `slots`. That is prompt quality for T4.3 to fix, not a schema issue.
`maxItems` is accepted (no 4xx); whether it is enforced server-side was not tested (needs >8 items).

Verdict: both frozen schemas accepted and validated on the fast tier; T4.0 needs no change.
Script (throwaway, not committed): scratchpad `pf1b.py`.
