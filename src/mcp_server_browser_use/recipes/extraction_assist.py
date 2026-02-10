"""JMESPath extraction assist for JSON responses.

Goal: generate deterministic, bounded candidate JMESPath expressions (`extract_path`)
from a JSON-like response structure.

These candidates are intended to be shown to an LLM for selection (or small edits),
so the LLM does not need to invent JMESPath from scratch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TypeAlias

DEFAULT_MAX_DEPTH = 6
DEFAULT_MAX_CANDIDATES = 20

_MAX_VISITED_NODES = 750
_MAX_LIST_SAMPLE = 6
_MAX_FIELDS_PER_LIST = 6

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JsonPath: TypeAlias = tuple[str, ...]  # keys and the special wildcard segment "[]"


@dataclass(frozen=True, slots=True)
class ExtractPathCandidate:
    expression: str
    score: int
    reason: str


_COLLECTION_KEY_WEIGHTS: dict[str, int] = {
    # Common API response list container keys.
    "items": 120,
    "results": 115,
    "data": 90,  # sometimes a list directly
    "value": 80,
    "values": 80,
    "records": 80,
    "rows": 75,
    "list": 70,
    "entries": 70,
    "elements": 65,
    # Search-ish.
    "hits": 75,
    "documents": 65,
    # GraphQL-ish.
    "edges": 85,
    "nodes": 85,
}

_WRAPPER_KEY_WEIGHTS: dict[str, int] = {
    # Common wrapper keys that often contain the "real" data.
    "data": 70,
    "payload": 55,
    "response": 45,
    "result": 45,
    "body": 40,
}


def generate_extract_path_candidates(
    value: JSONValue,
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[str]:
    """Generate candidate JMESPath expressions for extracting useful data from JSON.

    Deterministic:
    - Dict keys traversed in sorted order.
    - Candidate ordering uses score desc, expression asc.

    Bounded:
    - Traversal is depth-limited.
    - Candidate count capped by `max_candidates`.
    """
    if max_candidates <= 0:
        raise ValueError("max_candidates must be > 0")
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")

    acc = _CandidateAccumulator()

    # Special-case root list: `@` is too vague, prefer explicit projection.
    if isinstance(value, list):
        acc.add(ExtractPathCandidate(expression="[*]", score=200, reason="root_list"))

    visited = 0

    def walk(node: JSONValue, path: JsonPath, depth: int) -> None:
        nonlocal visited
        visited += 1
        if visited > _MAX_VISITED_NODES:
            return

        if depth > max_depth:
            return

        if isinstance(node, dict):
            _maybe_add_wrapper_candidate(acc, path)

            for key in sorted(node.keys()):
                child = node[key]
                walk(child, (*path, key), depth + 1)
            return

        if isinstance(node, list):
            _add_list_candidates(acc, node, path)
            for child in node[:_MAX_LIST_SAMPLE]:
                walk(child, (*path, "[]"), depth + 1)
            return

    walk(value, (), 0)

    # Present to LLM: only expressions, no reasons.
    return [c.expression for c in acc.best(max_candidates=max_candidates)]


class _CandidateAccumulator:
    def __init__(self) -> None:
        self._by_expr: dict[str, ExtractPathCandidate] = {}

    def add(self, candidate: ExtractPathCandidate) -> None:
        existing = self._by_expr.get(candidate.expression)
        if existing is None:
            self._by_expr[candidate.expression] = candidate
            return
        if candidate.score > existing.score:
            self._by_expr[candidate.expression] = candidate

    def best(self, *, max_candidates: int) -> list[ExtractPathCandidate]:
        all_candidates = list(self._by_expr.values())
        all_candidates.sort(key=lambda c: (-c.score, c.expression))
        return all_candidates[:max_candidates]


def _maybe_add_wrapper_candidate(acc: _CandidateAccumulator, path: JsonPath) -> None:
    if not path:
        return
    last = path[-1]
    if last == "[]":
        return
    weight = _WRAPPER_KEY_WEIGHTS.get(last.lower())
    if weight is None:
        return
    expr = _path_to_jmespath(path)
    acc.add(ExtractPathCandidate(expression=expr, score=weight, reason=f"wrapper:{last.lower()}"))


def _add_list_candidates(acc: _CandidateAccumulator, node: list[JSONValue], path: JsonPath) -> None:
    base_score = _score_list_path(path, node)
    # Candidate for extracting the list itself (e.g. `data.items`).
    # Root-list is special-cased to avoid emitting `@` (too vague).
    if path:
        base_expr = _path_to_jmespath(path)
        acc.add(ExtractPathCandidate(expression=base_expr, score=base_score, reason="list"))

    analysis = _analyze_list_items(node)
    if not analysis.common_object_keys:
        return

    # Candidate field projections (e.g. `items[*].name`).
    for key, key_score in analysis.top_field_keys:
        expr = _path_to_jmespath((*path, "[]", key))
        # Prefer extracting the full collection first. Field projections are useful,
        # but should generally rank below the raw list container.
        score = base_score - 60 + key_score
        acc.add(ExtractPathCandidate(expression=expr, score=score, reason=f"field:{key.lower()}"))

    # GraphQL-ish edges[*].node and node.<field>.
    if analysis.node_child_keys:
        node_expr = _path_to_jmespath((*path, "[]", "node"))
        acc.add(ExtractPathCandidate(expression=node_expr, score=base_score + 60, reason="graphql_node"))

        for key, key_score in analysis.top_node_field_keys:
            expr = _path_to_jmespath((*path, "[]", "node", key))
            score = base_score + 60 + key_score
            acc.add(ExtractPathCandidate(expression=expr, score=score, reason=f"graphql_node_field:{key.lower()}"))

    # Multi-select hash for a compact "record" shape.
    hash_expr = _maybe_build_multiselect_hash(path, analysis)
    if hash_expr is not None:
        acc.add(ExtractPathCandidate(expression=hash_expr, score=base_score - 20, reason="hash"))


def _score_list_path(path: JsonPath, node: list[JSONValue]) -> int:
    base = 40
    if not path:
        return base

    last_key = next((seg for seg in reversed(path) if seg != "[]"), "")
    if last_key:
        base += _COLLECTION_KEY_WEIGHTS.get(last_key.lower(), 0)

    length = len(node)
    if length >= 2:
        base += 10
    if length >= 10:
        base += 10

    if any(isinstance(v, dict) for v in node[:_MAX_LIST_SAMPLE]):
        base += 10

    # Prefer shorter / higher-level paths when scoring is otherwise equal.
    depth_penalty = len(path) * 2
    return max(0, base - depth_penalty)


@dataclass(frozen=True, slots=True)
class _ListAnalysis:
    common_object_keys: tuple[str, ...]
    top_field_keys: tuple[tuple[str, int], ...]  # (key, score)
    node_child_keys: tuple[str, ...]
    top_node_field_keys: tuple[tuple[str, int], ...]


def _analyze_list_items(node: list[JSONValue]) -> _ListAnalysis:
    dict_items: list[dict[str, JSONValue]] = []
    for v in node[:_MAX_LIST_SAMPLE]:
        if isinstance(v, dict):
            dict_items.append(v)

    if not dict_items:
        return _ListAnalysis(common_object_keys=(), top_field_keys=(), node_child_keys=(), top_node_field_keys=())

    key_counts: dict[str, int] = {}
    for item in dict_items:
        for k in item:
            key_counts[k] = key_counts.get(k, 0) + 1

    # Stable ordering: most frequent keys first, then lexicographically.
    keys_by_freq = sorted(key_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    common_keys = tuple(k for k, _ in keys_by_freq[:20])

    scored_fields = [(_field_score(k) + key_counts[k] * 3, k) for k in common_keys]
    scored_fields.sort(key=lambda sk: (-sk[0], sk[1]))
    top_fields = tuple((k, score) for score, k in scored_fields[:_MAX_FIELDS_PER_LIST])

    node_keys: list[dict[str, JSONValue]] = []
    for item in dict_items:
        child = item.get("node")
        if isinstance(child, dict):
            node_keys.append(child)

    node_child_key_counts: dict[str, int] = {}
    for child in node_keys:
        for k in child:
            node_child_key_counts[k] = node_child_key_counts.get(k, 0) + 1
    node_child_keys_sorted = sorted(node_child_key_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    node_child_keys = tuple(k for k, _ in node_child_keys_sorted[:20])

    scored_node_fields = [(_field_score(k) + node_child_key_counts[k] * 3, k) for k in node_child_keys]
    scored_node_fields.sort(key=lambda sk: (-sk[0], sk[1]))
    top_node_fields = tuple((k, score) for score, k in scored_node_fields[:_MAX_FIELDS_PER_LIST])

    return _ListAnalysis(
        common_object_keys=common_keys,
        top_field_keys=top_fields,
        node_child_keys=node_child_keys,
        top_node_field_keys=top_node_fields,
    )


def _field_score(key: str) -> int:
    kl = key.lower()

    if kl == "node":
        return 55

    # IDs.
    if kl in {"id", "uuid", "gid"}:
        return 50
    if kl.endswith("_id") or kl.endswith("id"):
        return 42

    # Human-facing labels.
    if kl in {"name", "title", "label"}:
        return 45
    if "name" in kl:
        return 35
    if "title" in kl:
        return 33

    # Links.
    if kl in {"url", "html_url", "link", "href"}:
        return 30
    if "url" in kl or "link" in kl or "href" in kl:
        return 22

    # Descriptions.
    if kl in {"description", "summary", "desc"}:
        return 26

    # Counts.
    if kl in {"count", "total", "size"}:
        return 20
    if "count" in kl or "total" in kl:
        return 16

    # Timestamps.
    if "created" in kl or "updated" in kl or "date" in kl or "time" in kl:
        return 12

    return 5


def _maybe_build_multiselect_hash(path: JsonPath, analysis: _ListAnalysis) -> str | None:
    # Only build from identifier-like keys so output object keys are stable and valid.
    chosen: list[str] = []
    for key, _ in analysis.top_field_keys:
        if _is_identifier(key):
            chosen.append(key)
        if len(chosen) >= 4:
            break

    if len(chosen) < 2:
        return None

    pairs = ", ".join(f"{k}: {k}" for k in chosen)
    if not path:
        return f"[*].{{{pairs}}}"
    base = _path_to_jmespath(path)
    return f"{base}[*].{{{pairs}}}"


def _is_identifier(key: str) -> bool:
    return _IDENTIFIER_RE.match(key) is not None


def _escape_quoted_identifier(key: str) -> str:
    # JMESPath string literal syntax matches JSON string escaping.
    # Use json.dumps-like escaping to handle control characters deterministically.
    dumped = json.dumps(key, ensure_ascii=False)
    # json.dumps always returns a quoted JSON string for str inputs.
    return dumped[1:-1]


def _path_to_jmespath(path: JsonPath) -> str:
    if not path:
        return "@"

    out = ""
    for seg in path:
        if seg == "[]":
            if not out:
                out = "[*]"
            else:
                out += "[*]"
            continue

        if not out:
            out = seg if _is_identifier(seg) else f'"{_escape_quoted_identifier(seg)}"'
            continue

        out += f".{seg}" if _is_identifier(seg) else f'."{_escape_quoted_identifier(seg)}"'

    return out or "@"
