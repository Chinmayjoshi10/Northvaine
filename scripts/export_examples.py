"""Build the landing page's example radars: finished runs, made safe, as static JSON.

  uv run python scripts/export_examples.py --source <folder> --out frontend/public/examples

`--source` holds what a finished run leaves behind: `<client>.json` (the client spec) and
`<client>/<day>/run.json`. `scripts/examples/config.json` says which runs become examples, what
each is called, and which brand words must never appear. Nothing about an industry lives here;
the words are in that data file.

What is published is only what the app's own pages show, produced through the same in-process API
as scripts/export_static.py, after a run has been made safe:

- every entry or set-aside item that names a forbidden word is dropped (the sanitizer's rule);
- company contact details are removed, and the client's customer and target lists are emptied;
- any evidence item whose text looks like it is about a person (a title, "said", a courtesy
  title) is dropped whole, so an unverifiable name can never reach the page;
- the finished files are checked again: no email address, phone number, forbidden word or
  person-looking text may remain, or nothing is written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from export_static import export  # noqa: E402
from sanitize_demo_report import problems, sanitize  # noqa: E402

CONFIG = Path(__file__).resolve().parent / "examples" / "config.json"
CLIENT_PREFIX = "example-"

# Text that is about a person, not a company: job titles, courtesy titles, quoted speech.
PERSON_RE = re.compile(
    r"(?-i:(?<![A-Za-z])(?:CEO|CFO|COO|CTO)(?![a-z]))"  # also glued to a word ("CEOFounded")
    r"|(?i:\b(?:chairman|chairwoman|president|founder|founders|co-founder|founded\b.{0,20}\bby|"
    r"run by|led by|managing director|director|directors|chief|officer|appointed|"
    r"resigned|mr|mrs|ms|miss|dr|said|says|told|born|spokesperson|spokesman|head of|"
    r"he|she|his|her|him|wife|husband|family|son|daughter|"
    r"married|partner and|sales manager|account manager|contact us|meet the team)\b)"
)
COMPANY_SUFFIX = re.compile(
    r"\b(ltd|limited|llp|lp|plc|inc|corp|corporation|gmbh|ag|sa|bv|nv|llc|holdings|group|"
    r"company|co|bidco|topco|midco)\b\.?",
    re.IGNORECASE,
)
STRENGTH_ORDER = {"strong": 0, "medium": 1, "weak": 2}


def _is_personal(value: Any) -> bool:
    return isinstance(value, str) and bool(PERSON_RE.search(value))


def scrub(obj: Any) -> Any:
    """Drop, at any depth, list items (dicts or strings) whose text reads as about a person."""
    if isinstance(obj, list):
        kept = []
        for item in obj:
            if isinstance(item, str):
                if _is_personal(item):
                    continue
            elif isinstance(item, dict) and any(_is_personal(v) for v in item.values()):
                continue
            kept.append(scrub(item))
        return kept
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


# Evidence is quoted exactly, so a brand inside a quote or a link cannot be reworded; every
# other string (the model's own reasons) says "this client" in the brand's place.
EVIDENCE_KEYS = {
    "url", "source_quote", "quote", "statement", "description", "final_url", "lead_url",
    "company_site", "line", "term", "title", "text",
}  # fmt: skip


def anonymise(obj: Any, words: list[str], key: str = "") -> Any:
    """Replace each brand word, outside quoted evidence, with "this client"."""
    if isinstance(obj, str):
        if key in EVIDENCE_KEYS:
            return obj
        for w in sorted(words, key=len, reverse=True):
            obj = re.sub(rf"\b{re.escape(w)}\b", "this client", obj, flags=re.IGNORECASE)
        return obj
    if isinstance(obj, list):
        return [anonymise(i, words, key) for i in obj]
    if isinstance(obj, dict):
        return {k: anonymise(v, words, k) for k, v in obj.items()}
    return obj


def _tidy_entry(entry: dict[str, Any]) -> dict[str, Any]:
    entry["company_contact"] = None
    opportunity = entry.get("opportunity")
    if opportunity and isinstance(opportunity.get("words"), str):  # runs saved before the fix
        opportunity["words"] = opportunity["words"].replace("1 source agree", "1 source agrees")
    entry = scrub(entry)
    candidate = entry["candidate"]
    refs = {c["ref"] for c in candidate["claims"]}
    candidate["events"] = [
        {**e, "claim_refs": [r for r in e["claim_refs"] if r in refs]}
        for e in candidate["events"]
        if any(r in refs for r in e["claim_refs"])
    ]
    register = candidate.get("company_register")
    if register:  # control by a person is a person's name: keep company owners only
        register["controlled_by"] = [
            n for n in register.get("controlled_by", []) if COMPANY_SUFFIX.search(n)
        ]
    quote = entry.get("site_role_quote")
    if entry.get("site_role") and not quote:  # a role without its quote is not a verified role
        entry["site_role"] = None
    for key in ("site_role_quote",):
        if _is_personal(json.dumps(entry.get(key) or "")):
            entry[key] = None
            entry["site_role"] = None
    return entry


def curate(run: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """(the safe example run, entries before, entries kept). Entries are the strongest first."""
    words = [w.casefold() for w in cfg["forbid"]]
    run, _ = sanitize(anonymise(run, words), words)
    entries = run["entries"]
    before = len(entries)
    if any((e.get("opportunity") or {}).get("held") is not None for e in entries) or any(
        "held" in (e.get("opportunity") or {}) for e in entries
    ):
        # D148 runs: the radar's own order, leads first, then held entries with their reasons
        def held(e: dict[str, Any]) -> bool:
            return bool((e.get("opportunity") or {}).get("held"))

        entries.sort(key=lambda e: (held(e), e["rank"]))
        chosen = entries[: cfg["keep"]]
    else:
        entries.sort(key=lambda e: (STRENGTH_ORDER.get(e["strength"], 3), e["rank"]))
        solid = [e for e in entries if e["strength"] != "weak"]
        chosen = (solid if len(solid) >= 3 else entries)[: cfg["keep"]]
    chosen = [_tidy_entry(e) for e in chosen]
    for n, entry in enumerate(chosen, start=1):
        entry["rank"] = n
    run["entries"] = chosen
    run["client_id"] = CLIENT_PREFIX + cfg["slug"]
    run["client_name"] = cfg["name"]
    run["offer"] = cfg["offer"]
    run["notes"] = []
    run["queries"] = {}
    run["found_by"] = {}
    return run, before, len(chosen)


def example_spec(spec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    words = [w.casefold() for w in cfg["forbid"]]
    spec = {
        k: [t for t in v if not (isinstance(t, str) and any(w in t.casefold() for w in words))]
        if isinstance(v, list)
        else v
        for k, v in spec.items()
    }
    spec = {**spec, "id": CLIENT_PREFIX + cfg["slug"], "name": cfg["name"], "offer": cfg["offer"]}
    spec["existing_customers"] = []
    spec["target_accounts"] = []
    spec["catalogue_lines"] = []
    spec["peer_sites"] = []
    # D158: keep which official sources cover which market (for the coverage line), nothing else
    # of the searches: no search text, no codes, no domains
    official = ("hmrc", "fts", "ted", "usaspending", "worldbank")
    spec["sensors"] = {
        name: [{"schema_ver": 1, "countries": q.get("countries", [])} for q in queries]
        for name, queries in (spec.get("sensors") or {}).items()
        if name in official
    }
    return spec


def _all_strings(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for item in obj for s in _all_strings(item)]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() for s in [str(k), *_all_strings(v)]]
    return []


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.+Z-]*)?$")


def _without_dates(obj: Any) -> Any:
    """Dates and timestamps look like phone numbers to the contact check; they carry no contact."""
    if isinstance(obj, str):
        return "" if DATE_RE.match(obj) else obj
    if isinstance(obj, list):
        return [_without_dates(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _without_dates(v) for k, v in obj.items()}
    return obj


def check_published(files: dict[str, Any], words: list[str]) -> list[str]:
    """What still makes the finished files unsafe (counts and paths only, never the text)."""
    found: list[str] = []
    for name, payload in files.items():
        for issue in problems(_without_dates(payload), words):
            found.append(f"{name}: {issue}")
        for text in _all_strings(payload):
            hit = PERSON_RE.search(text)
            if hit:  # the matched word and a little around it: public text, shown to the builder
                around = text[max(0, hit.start() - 40) : hit.end() + 40]
                found.append(f"{name}: person-looking text: ...{around}...")
    return found


def build(source: Path, out: Path, config: Path = CONFIG) -> list[str]:
    from northvaine.core.settings import get_settings

    cfgs = json.loads(config.read_text(encoding="utf-8"))["examples"]
    forbid = sorted({w.casefold() for c in cfgs for w in c["forbid"]})
    with tempfile.TemporaryDirectory() as tmp:
        reports, clients = Path(tmp) / "radar", Path(tmp) / "clients"
        clients.mkdir(parents=True)
        index = []
        for cfg in cfgs:
            # every example is cleaned of every example's brand words: one radar may name
            # another example's business (as a competitor), which would undo its anonymity
            cfg = {**cfg, "forbid": forbid}
            run_path = source / cfg["source"] / cfg["day"] / "run.json"
            run, before, _kept = curate(json.loads(run_path.read_text(encoding="utf-8")), cfg)
            spec = json.loads((source / f"{cfg['source']}.json").read_text(encoding="utf-8"))
            cid = CLIENT_PREFIX + cfg["slug"]
            (clients / f"{cid}.json").write_text(
                json.dumps(example_spec(spec, cfg)), encoding="utf-8"
            )
            folder = reports / cid / cfg["day"]
            folder.mkdir(parents=True)
            (folder / "run.json").write_text(json.dumps(run), encoding="utf-8")
            index.append(
                {
                    "client": cid,
                    "industry": cfg["industry"],
                    "name": cfg["name"],
                    "summary": cfg["summary"],
                    "day": cfg["day"],
                    # leads with proof (not held by the evidence floor or the review), D148
                    "shown": sum(
                        1 for e in run["entries"] if not (e.get("opportunity") or {}).get("held")
                    ),
                    "found": before + len(run["rejected"]),
                    "set_aside": len(run["rejected"]),
                }
            )
        os.environ["RADAR_CLIENTS_DIR"] = str(clients)
        os.environ["ONBOARDING_CLIENTS_DIR"] = str(clients)
        get_settings.cache_clear()
        scratch = Path(tmp) / "site"
        written = export(reports, scratch)
        files = {w: json.loads((scratch / w).read_text(encoding="utf-8")) for w in written}
        files["index.json"] = index
        left = check_published(files, forbid)
        if left:
            raise SystemExit("UNSAFE, nothing written:\n  " + "\n  ".join(left[:20]))
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(scratch, out)
        (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)
    written = build(args.source.resolve(), args.out.resolve(), args.config)
    print(f"exported {len(written)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
