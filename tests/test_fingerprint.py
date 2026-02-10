from __future__ import annotations

from mcp_server_browser_use.recipes.fingerprint import (
    JsonValueType,
    TypedJsonPath,
    fingerprint,
    fingerprint_similarity,
    fingerprints_similar,
    jaccard_similarity,
    json_similar,
)


def test_fingerprint_golden_basic_object() -> None:
    value = {
        "a": 1,
        "b": [{"c": "x"}],
        "d": None,
        "e": {"f": True},
    }

    got = fingerprint(value)
    expected = frozenset(
        {
            TypedJsonPath(path=(), value_type=JsonValueType.OBJECT),
            TypedJsonPath(path=("a",), value_type=JsonValueType.NUMBER),
            TypedJsonPath(path=("b",), value_type=JsonValueType.ARRAY),
            TypedJsonPath(path=("b", "[]"), value_type=JsonValueType.OBJECT),
            TypedJsonPath(path=("b", "[]", "c"), value_type=JsonValueType.STRING),
            TypedJsonPath(path=("d",), value_type=JsonValueType.NULL),
            TypedJsonPath(path=("e",), value_type=JsonValueType.OBJECT),
            TypedJsonPath(path=("e", "f"), value_type=JsonValueType.BOOLEAN),
        }
    )
    assert got == expected


def test_fingerprint_golden_list_indices_collapsed() -> None:
    value = {
        "arr": [
            {"x": 1},
            {"x": 2},
        ]
    }
    got = fingerprint(value)

    # The ("arr","[]","x") path should only appear once due to wildcard indexing.
    assert TypedJsonPath(path=("arr", "[]", "x"), value_type=JsonValueType.NUMBER) in got
    assert len([p for p in got if p.path == ("arr", "[]", "x")]) == 1


def test_fingerprint_depth_limit_stops_descent() -> None:
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}

    got = fingerprint(deep, max_depth=6)

    assert TypedJsonPath(path=("a", "b", "c", "d", "e", "f"), value_type=JsonValueType.OBJECT) in got
    assert TypedJsonPath(path=("a", "b", "c", "d", "e", "f", "g"), value_type=JsonValueType.NUMBER) not in got


def test_jaccard_similarity_empty_sets() -> None:
    assert jaccard_similarity(set[TypedJsonPath](), set[TypedJsonPath]()) == 1.0


def test_similarity_threshold_true_for_same_shape() -> None:
    a = {"id": 1, "name": "x", "tags": ["a", "b"], "meta": {"foo": True, "bar": None}}
    b = {"id": 2, "name": "y", "tags": ["c"], "meta": {"foo": False, "bar": None}}

    fa = fingerprint(a)
    fb = fingerprint(b)

    assert fingerprint_similarity(fa, fb) == 1.0
    assert fingerprints_similar(fa, fb, threshold=0.85)
    assert json_similar(a, b, threshold=0.85)


def test_similarity_threshold_false_for_different_shape() -> None:
    a = {"id": 1, "name": "x", "tags": ["a", "b"], "meta": {"foo": True, "bar": None}}
    b = {"id": "1", "name": {"first": "x"}}

    assert not json_similar(a, b, threshold=0.85)
