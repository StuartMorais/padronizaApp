from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from typing import Iterable


VECTOR_SIZE = 384


def normalize_semantic_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"\b\d{1,6}[./-]\d{1,6}(?:[./-]\d{2,4})?\b", " <num> ", text)
    text = re.sub(r"\b\d+(?:[.,]\d+)?\b", " <num> ", text)
    text = re.sub(r"[^a-z0-9<>]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _features(text: str) -> Iterable[tuple[str, float]]:
    normalized = normalize_semantic_text(text)
    if not normalized:
        return ()
    words = normalized.split()
    output: list[tuple[str, float]] = []
    for word in words:
        output.append((f"w:{word}", 1.8))
    for left, right in zip(words, words[1:]):
        output.append((f"b:{left}_{right}", 2.1))
    compact = normalized.replace(" ", "_")
    if len(compact) >= 3:
        for index in range(len(compact) - 2):
            output.append((f"c:{compact[index:index + 3]}", 0.45))
    return output


def embed_text(value: object) -> tuple[float, ...]:
    vector = [0.0] * VECTOR_SIZE
    counts: Counter[str] = Counter()
    weights: dict[str, float] = {}
    for feature, weight in _features(str(value or "")):
        counts[feature] += 1
        weights[feature] = weight
    for feature, count in counts.items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "little", signed=False)
        index = raw % VECTOR_SIZE
        sign = -1.0 if (raw >> 8) & 1 else 1.0
        vector[index] += sign * weights[feature] * (1.0 + math.log(float(count)))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))
