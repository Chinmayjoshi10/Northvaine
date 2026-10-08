"""Experiment (D92): can a small trained classifier imitate or pre-filter the Nemotron gate?

Builds a labelled dataset from the offline radar replays (tests/fixtures/radar/<client>/), then
compares cheap classifiers against the gate's own decisions with grouped cross-validation.
Experiment only: it changes no product code and reads, never edits, the recordings.

Run (needs `uv sync --group experiments`; the embedding model downloads once from Hugging Face):
  uv run --group experiments python scripts/experiments/gate_classifier.py [--setfit] [--json out]

Labels: only LLM-decided gate rows (`by == "llm"`): "passed" or the `rejected_as` verdict.
Code rejections (unidentified, not an organisation) are counted and reported, never trained on.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from northvaine.radar.models import Candidate, load_client_spec  # noqa: E402

RECORDINGS = ROOT / "tests" / "fixtures" / "radar"
CLIENTS_DIR = ROOT / "tests" / "fixtures" / "clients"
CLIENTS = ["stone_supplier", "coldchain_maker", "packaging_supplier"]
PASSED = "passed"
SEED = 7


def _radar_script() -> Any:
    spec = importlib.util.spec_from_file_location("nv_radar_exp", ROOT / "scripts" / "radar.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def candidate_text(c: Candidate, *, with_name: bool) -> str:
    """What the gate sees, as one string: name, roles, claim statements and quotes, events."""
    parts: list[str] = []
    if with_name:
        parts.append(f"name: {c.name}")
    parts.append("roles: " + ", ".join(c.roles))
    parts.append("stream: " + c.stream.value)
    for claim in c.claims:
        parts.append(f"claim: {claim.statement} / {claim.source_quote}")
    for event in c.events:
        parts.append(f"event: {event.event_type} {event.description}")
    return "\n".join(parts)


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def build_dataset() -> tuple[list[dict[str, Any]], dict[str, Counter]]:
    """(rows, code-rejection counts per client). Row: client, name, label, text, text_noname."""
    radar = _radar_script()
    rows: list[dict[str, Any]] = []
    code_rejected: dict[str, Counter] = {}
    for client in CLIENTS:
        recording = radar.load_replay(RECORDINGS / client, client)
        run = asyncio.run(radar.run_replay(load_client_spec(client, CLIENTS_DIR), recording))
        code_rejected[client] = Counter()
        # entries exist only when the gate passed them, and a code decision never passes
        decided = [(e.candidate, PASSED, "llm") for e in run.entries]
        for r in run.rejected:
            label = r.gate.rejected_as.value if r.gate.rejected_as else PASSED
            decided.append((r.candidate, label, r.gate.by))
        for cand, label, by in decided:
            if by == "code":
                code_rejected[client][label] += 1
                continue
            rows.append(
                {
                    "client": client,
                    "name": cand.name,
                    "group": norm_name(cand.name),
                    "label": label,
                    "text": candidate_text(cand, with_name=True),
                    "text_noname": candidate_text(cand, with_name=False),
                }
            )
    return rows, code_rejected


# --- metrics --------------------------------------------------------------------------------


def metrics(y_true: list[str], y_pred: list[str], p_passed: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

    yb = np.array([y == PASSED for y in y_true], dtype=float)
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
        "passed_precision": precision_score(
            y_true, y_pred, pos_label=PASSED, average="binary", zero_division=0
        ),
        "passed_recall": recall_score(
            y_true, y_pred, pos_label=PASSED, average="binary", zero_division=0
        ),
        "brier": float(np.mean((p_passed - yb) ** 2)),
    }


def prefilter(y_true: list[str], p_passed: np.ndarray) -> dict[str, float]:
    """Highest threshold that keeps 95% (and 99%) of the Nemotron-passed rows; the share of all
    rows scoring below it is the share of gate calls saved. The threshold is chosen on the same
    scores it is measured on, so this is optimistic; the 0.99 figure is the safer one."""
    yb = np.array([y == PASSED for y in y_true])
    out: dict[str, float] = {}
    pos = np.sort(p_passed[yb])
    for tag, keep in (("0.95", 0.95), ("0.99", 0.99)):
        if len(pos) == 0:
            out[f"saved_at_{tag}"] = float("nan")
            continue
        cut = int(np.floor((1 - keep) * len(pos)))  # passed rows allowed to fall below
        thr = pos[min(cut, len(pos) - 1)]
        out[f"saved_at_{tag}"] = float(np.mean(p_passed < thr))
    return out


# --- models ---------------------------------------------------------------------------------


class Majority:
    def fit(self, X: list[str], y: list[str]) -> Majority:
        counts = Counter(y)
        self.top = counts.most_common(1)[0][0]
        self.p = counts[PASSED] / len(y)
        return self

    def predict(self, X: list[str]) -> list[str]:
        return [self.top] * len(X)

    def p_passed(self, X: list[str]) -> np.ndarray:
        return np.full(len(X), self.p)


class SkLR:
    """Features -> multinomial logistic regression, with p(passed) from predict_proba."""

    def __init__(self, features: Any, C: float = 5.0) -> None:
        from sklearn.linear_model import LogisticRegression

        self.features = features
        self.clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced")

    def fit(self, X: list[str], y: list[str]) -> SkLR:
        self.clf.fit(self.features.fit_transform(X), y)
        return self

    def predict(self, X: list[str]) -> list[str]:
        return list(self.clf.predict(self.features.transform(X)))

    def p_passed(self, X: list[str]) -> np.ndarray:
        if PASSED not in self.clf.classes_:
            return np.zeros(len(X))
        proba = self.clf.predict_proba(self.features.transform(X))
        return proba[:, list(self.clf.classes_).index(PASSED)]


def tfidf_lr() -> SkLR:
    from sklearn.feature_extraction.text import TfidfVectorizer

    return SkLR(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True))


_ENCODER: Any = None
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class _Embed:
    """Frozen sentence embeddings (no fitting), cached per text."""

    cache: dict[str, np.ndarray] = {}

    def fit_transform(self, X: list[str]) -> np.ndarray:
        return self.transform(X)

    def transform(self, X: list[str]) -> np.ndarray:
        global _ENCODER
        if _ENCODER is None:
            from sentence_transformers import SentenceTransformer

            _ENCODER = SentenceTransformer(EMBED_MODEL, device="cpu")
        todo = [x for x in dict.fromkeys(X) if x not in self.cache]
        if todo:
            vecs = _ENCODER.encode(todo, batch_size=32, normalize_embeddings=True)
            self.cache.update(zip(todo, vecs, strict=True))
        return np.stack([self.cache[x] for x in X])


def embed_lr() -> SkLR:
    return SkLR(_Embed(), C=10.0)


class SetFitModel:
    """SetFit on CPU: contrastive fine-tune of the sentence encoder, then a logistic head."""

    def fit(self, X: list[str], y: list[str]) -> SetFitModel:
        from datasets import Dataset
        from setfit import SetFitModel as SF
        from setfit import Trainer, TrainingArguments

        self.model = SF.from_pretrained(EMBED_MODEL, device="cpu")
        self.model.model_body.max_seq_length = 128  # long texts make CPU training too slow
        args = TrainingArguments(batch_size=16, num_iterations=3, num_epochs=1, seed=SEED)
        Trainer(
            model=self.model, args=args, train_dataset=Dataset.from_dict({"text": X, "label": y})
        ).train()
        return self

    def predict(self, X: list[str]) -> list[str]:
        return [str(v) for v in self.model.predict(X)]

    def p_passed(self, X: list[str]) -> np.ndarray:
        proba = np.asarray(self.model.predict_proba(X))
        classes = [str(c) for c in self.model.model_head.classes_]
        return proba[:, classes.index(PASSED)] if PASSED in classes else np.zeros(len(X))


# --- cross-validation -----------------------------------------------------------------------


def folds(rows: list[dict[str, Any]], scheme: str) -> list[tuple[list[int], list[int]]]:
    idx = np.arange(len(rows))
    if scheme == "loco":  # leave one client out
        return [
            ([i for i in idx if rows[i]["client"] != c], [i for i in idx if rows[i]["client"] == c])
            for c in CLIENTS
        ]
    # `passed` vs the rest is what matters; strata on the label keep rare verdicts spread out
    y = [r["label"] for r in rows]
    if scheme == "kfold":  # stratified; the same company may sit in train and test (leaky)
        from sklearn.model_selection import StratifiedKFold

        splitter = StratifiedKFold(5, shuffle=True, random_state=SEED).split(
            idx, [r["label"] if Counter(y)[r["label"]] >= 5 else "rare" for r in rows]
        )
        return [(list(a), list(b)) for a, b in splitter]
    if scheme == "groupkfold":  # stratified, and a company never spans train and test
        from sklearn.model_selection import StratifiedGroupKFold

        g = [r["group"] for r in rows]
        splitter = StratifiedGroupKFold(5, shuffle=True, random_state=SEED).split(idx, y, g)
        return [(list(a), list(b)) for a, b in splitter]
    raise ValueError(scheme)


def evaluate(rows: list[dict[str, Any]], make: Any, scheme: str, key: str) -> dict[str, Any]:
    y_true: list[str] = []
    y_pred: list[str] = []
    scores: list[float] = []
    for train, test in folds(rows, scheme):
        ytr = [rows[i]["label"] for i in train]
        if len(set(ytr)) < 2:
            continue
        model = make().fit([rows[i][key] for i in train], ytr)
        xte = [rows[i][key] for i in test]
        y_true += [rows[i]["label"] for i in test]
        y_pred += model.predict(xte)
        scores += list(model.p_passed(xte))
    s = np.array(scores)
    out = metrics(y_true, y_pred, s)
    out.update(prefilter(y_true, s))
    out["n"] = len(y_true)
    return out


ZS_MODEL = "MoritzLaurer/deberta-v3-xsmall-zeroshot-v1.1-all-33"


def zero_shot(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Binary zero-shot NLI: does the text describe an organisation that would buy (passed) or
    one that sells/publishes/competes (not passed)? Needs no labels, so it scores every row."""
    from transformers import pipeline

    clf = pipeline("zero-shot-classification", model=ZS_MODEL, device=-1)
    labels = ["a buyer or customer of products", "a seller, competitor, publisher or other"]
    scores = []
    for r in rows:
        out = clf(r["text_noname"][:1500], labels, multi_label=False)
        scores.append(dict(zip(out["labels"], out["scores"], strict=True))[labels[0]])
    s = np.array(scores)
    y_true = [r["label"] for r in rows]
    y_pred = [PASSED if v >= 0.5 else "not_a_buyer" for v in s]
    out_m = metrics(y_true, y_pred, s)
    out_m.update(prefilter(y_true, s))
    out_m["n"] = len(rows)
    return out_m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--setfit", action="store_true", help="also run SetFit (slow on CPU)")
    ap.add_argument("--zeroshot", action="store_true", help="also score an NLI zero-shot model")
    ap.add_argument("--json", type=Path, help="write the results here")
    ap.add_argument("--cache", type=Path, help="reuse/save the dataset here (replays take minutes)")
    args = ap.parse_args()

    if args.cache and args.cache.is_file():
        cached = json.loads(args.cache.read_text(encoding="utf-8"))
        rows, code_rejected = cached["rows"], {c: Counter(v) for c, v in cached["code"].items()}
    else:
        rows, code_rejected = build_dataset()
        if args.cache:
            args.cache.write_text(
                json.dumps({"rows": rows, "code": {c: dict(v) for c, v in code_rejected.items()}}),
                encoding="utf-8",
            )
    label_counts = Counter(r["label"] for r in rows)
    clients_of: dict[str, set[str]] = {}
    for r in rows:
        clients_of.setdefault(r["group"], set()).add(r["client"])
    multi_client = [g for g, cs in clients_of.items() if len(cs) > 1]
    dup_names = sum(1 for g, n in Counter(r["group"] for r in rows).items() if n > 1)
    print(f"rows (LLM-decided): {len(rows)}  labels: {dict(label_counts)}")
    print(f"code rejections (not labels): { {c: dict(v) for c, v in code_rejected.items()} }")
    for c in CLIENTS:
        print(f"  {c}: {dict(Counter(r['label'] for r in rows if r['client'] == c))}")
    print(
        f"names in more than one client: {len(multi_client)}; repeated names overall: {dup_names}"
    )

    models: dict[str, Any] = {
        "majority": Majority,
        "tfidf+LR": tfidf_lr,
        "minilm-embed+LR": embed_lr,
    }
    # SetFit fine-tunes the encoder per fold (minutes each on CPU): leave-one-client-out only.
    slow = {"setfit-minilm": SetFitModel} if args.setfit else {}
    results: dict[str, Any] = {
        "dataset": {
            "rows": len(rows),
            "labels": dict(label_counts),
            "code_rejected": {c: dict(v) for c, v in code_rejected.items()},
            "names_in_multiple_clients": len(multi_client),
            "repeated_names": dup_names,
        }
    }
    cols = [
        "accuracy",
        "macro_f1",
        "passed_precision",
        "passed_recall",
        "brier",
        "saved_at_0.95",
        "saved_at_0.99",
    ]
    for key, label in (("text", "with name"), ("text_noname", "name removed")):
        for scheme in ("loco", "groupkfold", "kfold"):
            print(f"\n== {scheme}, features: {label} ==")
            print(f"{'model':18s} " + " ".join(f"{c[:12]:>12s}" for c in cols))
            todo = dict(models)
            if scheme == "loco" and key == "text_noname":
                todo.update(slow)
            for name, make in todo.items():
                r = evaluate(rows, make, scheme, key)
                results[f"{scheme}|{key}|{name}"] = r
                print(f"{name:18s} " + " ".join(f"{r[c]:12.3f}" for c in cols))
    if args.zeroshot:
        results["zeroshot_nli"] = zero_shot(rows)
        print("\n== NLI zero-shot (no training; all rows) ==")
        print({k: round(v, 3) for k, v in results["zeroshot_nli"].items()})
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
