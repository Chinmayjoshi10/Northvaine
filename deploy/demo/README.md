# Public demo client

`clients/stone_exporter_demo.json` is generated from a private spec, never written by hand:

    uv run python scripts/make_demo_spec.py --source <private spec.json> \
        --out deploy/demo/clients/stone_exporter_demo.json --forbid <company word> --forbid <name word>

It sets the id and name, empties `existing_customers`, and refuses if a forbidden word survives.
Read the output by eye before committing it. See docs/HOSTING.md.
