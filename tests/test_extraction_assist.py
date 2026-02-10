from __future__ import annotations

import jmespath

from mcp_server_browser_use.recipes.extraction_assist import JSONValue, generate_extract_path_candidates


def test_candidates_simple_nested_items() -> None:
    value: JSONValue = {
        "data": {
            "items": [
                {"id": 1, "name": "alpha", "url": "https://example.com/a"},
                {"id": 2, "name": "beta", "url": "https://example.com/b"},
            ],
            "total": 2,
        }
    }

    got = generate_extract_path_candidates(value, max_candidates=20)

    assert got[0] == "data.items"
    assert "data.items[*].name" in got
    assert "data.items[*].id" in got
    assert jmespath.search("data.items[*].name", value) == ["alpha", "beta"]


def test_candidates_graphql_edges_node() -> None:
    value: JSONValue = {
        "data": {
            "search": {
                "edges": [
                    {"cursor": "c1", "node": {"id": "1", "title": "t1"}},
                    {"cursor": "c2", "node": {"id": "2", "title": "t2"}},
                ]
            }
        }
    }

    got = generate_extract_path_candidates(value, max_candidates=30)

    assert "data.search.edges" in got
    assert "data.search.edges[*].node" in got
    assert "data.search.edges[*].node.title" in got
    assert jmespath.search("data.search.edges[*].node.title", value) == ["t1", "t2"]


def test_candidates_root_list_projection() -> None:
    value: JSONValue = [
        {"id": 1, "name": "x"},
        {"id": 2, "name": "y"},
    ]

    got = generate_extract_path_candidates(value, max_candidates=15)

    assert got[0] == "[*]"
    assert "@" not in got
    assert "[*].name" in got
    assert jmespath.search("[*].name", value) == ["x", "y"]


def test_candidates_non_identifier_keys_use_quoted_identifiers() -> None:
    value: JSONValue = {
        "data-items": [
            {"full-name": "x"},
            {"full-name": "y"},
        ]
    }

    got = generate_extract_path_candidates(value, max_candidates=20)

    assert '"data-items"' in got
    assert '"data-items"[*]."full-name"' in got
    assert jmespath.search('"data-items"[*]."full-name"', value) == ["x", "y"]


def test_candidates_quoted_identifier_escapes_control_chars() -> None:
    value: JSONValue = {
        "data\nitems": [
            {"full\tname": "x"},
            {"full\tname": "y"},
        ]
    }

    got = generate_extract_path_candidates(value, max_candidates=25)

    assert '"data\\nitems"' in got
    assert '"data\\nitems"[*]."full\\tname"' in got
    assert jmespath.search('"data\\nitems"[*]."full\\tname"', value) == ["x", "y"]


def test_candidates_quoted_identifier_escapes_quotes_and_backslashes() -> None:
    value: JSONValue = {
        'data"\\items': [
            {'field"\\name': "x"},
            {'field"\\name': "y"},
        ]
    }

    got = generate_extract_path_candidates(value, max_candidates=40)

    # Sanity: ensure we actually generated quoted identifiers with escapes.
    assert any('\\"' in c for c in got)
    assert any("\\\\" in c for c in got)

    expected = ["x", "y"]
    for candidate in got:
        try:
            if jmespath.search(candidate, value) == expected:
                return
        except Exception:
            continue

    raise AssertionError(f"No candidate executed to expected value. candidates={got!r}")


def test_candidates_bounded_and_deterministic() -> None:
    value: JSONValue = {
        "data": {
            "results": [{"id": 1, "title": "a", "description": "x"}, {"id": 2, "title": "b", "description": "y"}],
            "meta": {"page": 1, "per_page": 20},
        }
    }

    got1 = generate_extract_path_candidates(value, max_candidates=5)
    got2 = generate_extract_path_candidates(value, max_candidates=5)

    assert got1 == got2
    assert len(got1) <= 5
