from __future__ import annotations

import hashlib
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Protocol

from .domain import canonical_sha256


MATH_BOUNDARY_SCHEMA = "casulo.math-boundary/1.0"
SIMILARITY_DIMENSIONS = 64
DEFAULT_ADOPTION_RATIO = 0.95


class SimilarityKernel(Protocol):
    kernel_id: str

    def prepare(self, tokens: set[str]) -> object: ...

    def cosine(self, left: object, right: object) -> float: ...


@dataclass(frozen=True, slots=True)
class SparseSignedVector:
    dimensions: int
    entries: tuple[tuple[int, float], ...]
    norm: float


@dataclass(frozen=True, slots=True)
class KernelEquivalenceReceipt:
    schema: str
    reference_kernel: str
    candidate_kernel: str
    cases: int
    max_absolute_difference: float
    tolerance: float
    passed: bool
    reference_output_hash: str
    candidate_output_hash: str
    receipt_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class KernelProfile:
    schema: str
    classification: str
    rounds: int
    pairs_per_round: int
    reference_median_ns: int
    candidate_median_ns: int
    candidate_reference_ratio: float
    adoption_ratio_threshold: float
    candidate_wins: bool
    reference_logical_slots: int
    candidate_logical_slots: int
    traffic_reduced: bool
    checksum: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DenseSignedCosine:
    """Reference implementation used by LivingMemory before ARC-8."""

    kernel_id = "living-memory/dense-signed-cosine-python-v1"

    def prepare(self, tokens: set[str]) -> tuple[float, ...]:
        vector = [0.0] * SIMILARITY_DIMENSIONS
        for token in tokens:
            index, sign = _coordinate(token)
            vector[index] += sign
        return tuple(vector)

    def cosine(self, left: object, right: object) -> float:
        if not isinstance(left, tuple) or not isinstance(right, tuple):
            raise TypeError("vetor denso inválido")
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return max(0.0, numerator / (left_norm * right_norm))


class SparseSignedCosine:
    """Same signed-hash cosine, without materializing zero coordinates."""

    kernel_id = "living-memory/sparse-signed-cosine-python-v1"

    def prepare(self, tokens: set[str]) -> SparseSignedVector:
        values: dict[int, float] = {}
        for token in tokens:
            index, sign = _coordinate(token)
            values[index] = values.get(index, 0.0) + sign
        entries = tuple(sorted((index, value) for index, value in values.items() if value))
        return SparseSignedVector(
            dimensions=SIMILARITY_DIMENSIONS,
            entries=entries,
            norm=math.sqrt(sum(value * value for _, value in entries)),
        )

    def cosine(self, left: object, right: object) -> float:
        if not isinstance(left, SparseSignedVector) or not isinstance(right, SparseSignedVector):
            raise TypeError("vetor esparso inválido")
        if left.dimensions != right.dimensions or left.dimensions != SIMILARITY_DIMENSIONS:
            raise ValueError("dimensão esparsa incompatível")
        if not left.norm or not right.norm:
            return 0.0
        left_index = dict(left.entries)
        numerator = sum(left_index.get(index, 0.0) * value for index, value in right.entries)
        return max(0.0, numerator / (left.norm * right.norm))


def mathematical_boundary_inventory() -> Mapping[str, Any]:
    """Truthful inventory: decision authority and arithmetic implementation differ."""

    return {
        "schema": MATH_BOUNDARY_SCHEMA,
        "claim_class": "PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK",
        "boundaries": [
            {
                "id": "owner-neural-inference",
                "implementation": "Qwen3-4B GGUF via llama.cpp/ggml",
                "authority": "FOREIGN_NUMERICAL_PRIMITIVE_UNDER_CASULO_POLICY",
                "arc8_action": "MANIFEST_ONLY",
            },
            {
                "id": "owner-asr",
                "implementation": "Whisper model via whisper.cpp/ggml",
                "authority": "FOREIGN_NUMERICAL_PRIMITIVE_UNDER_CASULO_POLICY",
                "arc8_action": "MANIFEST_ONLY",
            },
            {
                "id": "living-memory-similarity",
                "implementation": DenseSignedCosine.kernel_id,
                "authority": "FIRST_PARTY_PRODUCT_KERNEL",
                "arc8_action": "EQUIVALENT_SPECIALIZATION_GOVERNED_BY_T",
            },
            {
                "id": "einstein-local-evaluator",
                "implementation": "owner Python 4D bounded differential geometry kernel",
                "authority": "FIRST_PARTY_DOMAIN_ADAPTER",
                "arc8_action": "OUT_OF_GENERIC_OWNER_HOT_PATH",
            },
            {
                "id": "historical-tensor-stack",
                "implementation": "T tensor JSON IR plus C99/OpenMP backend",
                "authority": "RESEARCH_STACK_NOT_OWNER_RUNTIME_PATH",
                "arc8_action": "NO_SOVEREIGNTY_CLAIM",
            },
        ],
        "forbidden_claims": [
            "T replaces Qwen or llama.cpp matrix kernels",
            "universal linear algebra superiority",
            "scientific or energetic advantage",
            "the historical tensor extension is the current owner inference path",
        ],
    }


def verify_similarity_equivalence(
    cases: Iterable[tuple[set[str], set[str]]] | None = None,
    *,
    tolerance: float = 1e-15,
) -> KernelEquivalenceReceipt:
    reference = DenseSignedCosine()
    candidate = SparseSignedCosine()
    selected_cases = tuple(cases or _qualification_cases())
    reference_outputs = tuple(reference.cosine(reference.prepare(left), reference.prepare(right)) for left, right in selected_cases)
    candidate_outputs = tuple(candidate.cosine(candidate.prepare(left), candidate.prepare(right)) for left, right in selected_cases)
    maximum = max((abs(left - right) for left, right in zip(reference_outputs, candidate_outputs)), default=0.0)
    seed = {
        "schema": "casulo.math-kernel-equivalence/1.0",
        "reference_kernel": reference.kernel_id,
        "candidate_kernel": candidate.kernel_id,
        "cases": len(selected_cases),
        "max_absolute_difference": maximum,
        "tolerance": tolerance,
        "passed": maximum <= tolerance,
        "reference_output_hash": canonical_sha256(reference_outputs),
        "candidate_output_hash": canonical_sha256(candidate_outputs),
    }
    return KernelEquivalenceReceipt(**seed, receipt_hash=canonical_sha256(seed))


def profile_similarity_kernels(
    *,
    rounds: int = 7,
    repetitions: int = 400,
    adoption_ratio_threshold: float = DEFAULT_ADOPTION_RATIO,
) -> KernelProfile:
    """Short local product diagnostic; never an energy or scientific benchmark."""

    if rounds < 3 or repetitions < 1 or not 0 < adoption_ratio_threshold < 1:
        raise ValueError("configuração de perfil inválida")
    pairs = _qualification_cases()
    reference = DenseSignedCosine()
    candidate = SparseSignedCosine()
    reference_times: list[int] = []
    candidate_times: list[int] = []
    checksum = 0.0
    for round_index in range(rounds):
        order = ((reference, reference_times), (candidate, candidate_times))
        if round_index % 2:
            order = tuple(reversed(order))
        for kernel, samples in order:
            started = time.perf_counter_ns()
            local = 0.0
            for _ in range(repetitions):
                for left, right in pairs:
                    local += kernel.cosine(kernel.prepare(left), kernel.prepare(right))
            samples.append(time.perf_counter_ns() - started)
            checksum += local
    reference_median = int(statistics.median(reference_times))
    candidate_median = int(statistics.median(candidate_times))
    ratio = candidate_median / reference_median if reference_median else math.inf
    reference_slots = len(pairs) * SIMILARITY_DIMENSIONS * 2
    sparse = SparseSignedCosine()
    candidate_slots = sum(
        len(sparse.prepare(left).entries) + len(sparse.prepare(right).entries)
        for left, right in pairs
    )
    return KernelProfile(
        schema="casulo.math-kernel-profile/1.0",
        classification="SHORT_PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK",
        rounds=rounds,
        pairs_per_round=len(pairs) * repetitions,
        reference_median_ns=reference_median,
        candidate_median_ns=candidate_median,
        candidate_reference_ratio=ratio,
        adoption_ratio_threshold=adoption_ratio_threshold,
        candidate_wins=ratio < adoption_ratio_threshold,
        reference_logical_slots=reference_slots,
        candidate_logical_slots=candidate_slots,
        traffic_reduced=candidate_slots < reference_slots,
        checksum=checksum,
    )


def _coordinate(token: str) -> tuple[int, float]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:2], "big") % SIMILARITY_DIMENSIONS, 1.0 if digest[2] & 1 else -1.0


def _qualification_cases() -> tuple[tuple[set[str], set[str]], ...]:
    phrases = (
        "casulo lembra decisão saturno azul",
        "decisão saturno azul projeto trânsito",
        "memória viva com proveniência verificável",
        "guia criativo conversa enquanto compila",
        "restrição hard nunca pode desaparecer",
        "universo intenção sinais engenharia materialização",
        "equações de campo tensor einstein métrica",
        "correção localizada preserva subgrafo aprovado",
        "voz presença interrupção barge in",
        "",
    )
    token_sets = tuple({word.casefold() for word in phrase.split() if len(word) > 1} for phrase in phrases)
    return tuple((token_sets[index], token_sets[(index * 3 + 1) % len(token_sets)]) for index in range(len(token_sets)))
