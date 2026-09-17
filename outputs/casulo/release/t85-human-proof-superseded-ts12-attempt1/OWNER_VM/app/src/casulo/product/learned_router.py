from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class LearnedRouterError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def features(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9_]+", normalized)
    result: list[str] = [f"w:{word}" for word in words]
    joined = "_".join(words)
    result.extend(f"c:{joined[index:index + 4]}" for index in range(max(0, len(joined) - 3)))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class RouterPrediction:
    universe_id: str
    confidence: float
    scores: Mapping[str, float]
    adapter_id: str


@dataclass(frozen=True, slots=True)
class LearnedRouterModel:
    model_id: str
    labels: tuple[str, ...]
    log_priors: Mapping[str, float]
    log_likelihoods: Mapping[str, Mapping[str, float]]
    unknown_log_likelihoods: Mapping[str, float]
    dataset_sha256: str
    training_split_sha256: str
    license: str

    @classmethod
    def load(cls, path: Path) -> "LearnedRouterModel":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "casulo.learned-semantic-router/1.0":
            raise LearnedRouterError("schema de router incompatível")
        expected = payload.pop("model_sha256", None)
        actual = sha256_bytes(canonical_bytes(payload))
        if expected != actual:
            raise LearnedRouterError("hash do adapter de router não confere")
        return cls(
            payload["model_id"], tuple(payload["labels"]), payload["log_priors"],
            payload["log_likelihoods"], payload["unknown_log_likelihoods"],
            payload["dataset_sha256"], payload["training_split_sha256"], payload["license"],
        )

    def predict(self, query: str, *, allowed_universes: Iterable[str] | None = None) -> RouterPrediction:
        allowed = set(self.labels if allowed_universes is None else allowed_universes)
        candidates = [label for label in self.labels if label in allowed]
        if not candidates:
            raise LearnedRouterError("nenhum universo permitido")
        counts = Counter(features(query))
        raw: dict[str, float] = {}
        for label in candidates:
            likelihood = self.log_likelihoods[label]
            raw[label] = self.log_priors[label] + sum(
                count * likelihood.get(token, self.unknown_log_likelihoods[label])
                for token, count in counts.items()
            )
        best = max(raw, key=raw.get)
        peak = max(raw.values())
        total = sum(math.exp(value - peak) for value in raw.values())
        confidence = math.exp(raw[best] - peak) / total
        return RouterPrediction(best, confidence, raw, self.model_id)


def train_router(dataset: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if dataset.get("schema") != "casulo.router-dataset/1.0" or dataset.get("contains_user_content") is not False:
        raise LearnedRouterError("dataset sem contrato first-party seguro")
    records = list(dataset.get("records", []))
    train = [item for item in records if item.get("split") == "train"]
    labels = tuple(sorted({str(item["universe"]) for item in train}))
    if len(labels) < 2:
        raise LearnedRouterError("treino precisa de múltiplas classes")
    families: dict[str, set[str]] = defaultdict(set)
    for item in records:
        families[str(item["split"])].add(str(item["family"]))
    if any(families[left] & families[right] for left in families for right in families if left < right):
        raise LearnedRouterError("scenario family vazou entre splits")
    class_docs = Counter(str(item["universe"]) for item in train)
    token_counts: dict[str, Counter[str]] = {label: Counter() for label in labels}
    vocabulary: set[str] = set()
    for item in train:
        tokens = features(str(item["text"]))
        token_counts[str(item["universe"])].update(tokens)
        vocabulary.update(tokens)
    total_docs = len(train)
    priors, likelihoods, unknowns = {}, {}, {}
    for label in labels:
        priors[label] = math.log(class_docs[label] / total_docs)
        denominator = sum(token_counts[label].values()) + len(vocabulary) + 1
        unknowns[label] = math.log(1 / denominator)
        likelihoods[label] = {token: math.log((count + 1) / denominator) for token, count in sorted(token_counts[label].items())}
    training_payload = [{key: item[key] for key in ("id", "family", "text", "universe")} for item in train]
    model = {
        "schema": "casulo.learned-semantic-router/1.0",
        "model_id": "casulo-semantic-router-nb-char4-v1",
        "role": "SemanticRouter",
        "architecture": "multinomial-naive-bayes-word-char4",
        "labels": list(labels),
        "log_priors": priors,
        "log_likelihoods": likelihoods,
        "unknown_log_likelihoods": unknowns,
        "dataset_sha256": sha256_bytes(canonical_bytes(dataset)),
        "training_split_sha256": sha256_bytes(canonical_bytes(training_payload)),
        "license": str(dataset["license"]),
        "upstream_weights": None,
        "user_content_used": False,
    }
    model["model_sha256"] = sha256_bytes(canonical_bytes(model))
    lineage = {
        "schema": "casulo.training-lineage/1.0",
        "dataset_sha256": model["dataset_sha256"],
        "training_split_sha256": model["training_split_sha256"],
        "train_records": len(train),
        "split_families": {key: sorted(value) for key, value in families.items()},
        "dedup_exact": len({str(item["text"]).casefold().strip() for item in records}) == len(records),
        "contains_user_content": False,
        "contains_rc3_holdout": dataset.get("contains_holdout_rc3"),
    }
    return model, lineage


def exact_name_baseline(query: str, labels: Iterable[str]) -> str:
    words = set(re.findall(r"[a-z0-9_]+", query.casefold()))
    ordered = tuple(sorted(labels))
    return next((label for label in ordered if label in words), "intencao")
