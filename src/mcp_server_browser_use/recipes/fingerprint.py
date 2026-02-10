"""JSON shape fingerprinting for recipe learning.

This module provides a small, pure-functional fingerprint for JSON-like values:
- Fingerprint = set of typed JSON paths (path + value type)
- Fingerprints compared via Jaccard similarity

Design goals:
- Stable across dict ordering
- Insensitive to list indices (uses a wildcard "[]")
- Depth limited (default: 6) to avoid overfitting and control cost
"""

from __future__ import annotations

from collections.abc import Hashable, Set
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias, TypeVar

DEFAULT_MAX_DEPTH = 6
DEFAULT_SIMILARITY_THRESHOLD = 0.85


JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JsonPath: TypeAlias = tuple[str, ...]


class JsonValueType(str, Enum):
    OBJECT = "object"
    ARRAY = "array"
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NULL = "null"


@dataclass(frozen=True, slots=True)
class TypedJsonPath:
    """A JSON path annotated with the runtime JSON value type at that path."""

    path: JsonPath
    value_type: JsonValueType


Fingerprint: TypeAlias = frozenset[TypedJsonPath]


def _classify_json_value(value: JSONValue) -> JsonValueType:
    if value is None:
        return JsonValueType.NULL
    if isinstance(value, bool):
        return JsonValueType.BOOLEAN
    if isinstance(value, (int, float)):
        # bool is a subclass of int, handled above
        return JsonValueType.NUMBER
    if isinstance(value, str):
        return JsonValueType.STRING
    if isinstance(value, dict):
        return JsonValueType.OBJECT
    if isinstance(value, list):
        return JsonValueType.ARRAY
    raise TypeError(f"Unsupported JSON value type: {type(value)!r}")


def fingerprint(value: JSONValue, *, max_depth: int = DEFAULT_MAX_DEPTH) -> Fingerprint:
    """Compute a typed JSON path fingerprint for a JSON-like value.

    - Paths for list items use a wildcard segment "[]", not numeric indices.
    - All nodes (including objects/arrays) are recorded with their type.
    - Traversal stops once `max_depth` is reached (depth counts path segments).
    """
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")

    out: set[TypedJsonPath] = set()

    def walk(node: JSONValue, path: JsonPath, depth: int) -> None:
        node_type = _classify_json_value(node)
        out.add(TypedJsonPath(path=path, value_type=node_type))

        if depth >= max_depth:
            return

        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, (*path, key), depth + 1)
            return

        if isinstance(node, list):
            for child in node:
                walk(child, (*path, "[]"), depth + 1)
            return

    walk(value, (), 0)
    return frozenset(out)


T = TypeVar("T", bound=Hashable)


def jaccard_similarity(a: Set[T], b: Set[T]) -> float:
    """Compute Jaccard similarity between two sets.

    J(A,B) = |A intersect B| / |A union B|
    If both are empty, returns 1.0.
    """
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def fingerprint_similarity(a: Fingerprint, b: Fingerprint) -> float:
    return jaccard_similarity(a, b)


def fingerprints_similar(
    a: Fingerprint,
    b: Fingerprint,
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    return fingerprint_similarity(a, b) >= threshold


def json_similarity(
    a: JSONValue,
    b: JSONValue,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> float:
    return fingerprint_similarity(fingerprint(a, max_depth=max_depth), fingerprint(b, max_depth=max_depth))


def json_similar(
    a: JSONValue,
    b: JSONValue,
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> bool:
    return json_similarity(a, b, max_depth=max_depth) >= threshold
